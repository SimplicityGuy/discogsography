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
3. **Blind Spots column** — flex column layout with blind spot list and "Download Taste Card" button anchored at the bottom via `margin-top: auto`.

### Responsive behavior

- At `<= 1024px`: collapse to 2 columns (fingerprint + heatmap on row 1, blind spots spanning full width on row 2)
- At `<= 640px`: stack all 3 columns vertically

## Preconditions

The taste strip only renders when **all** of the following are true:

1. User is authenticated (`authManager.getToken()` returns a token)
2. Discogs is connected (`authManager.getDiscogsStatus()?.connected === true`)
3. The `/fingerprint` API call succeeds (not 422, not error)

If any precondition fails, the `#tasteStrip` container remains empty/hidden.

## Data Flow

### On Collection pane switch

The fingerprint fetch is triggered from the `_switchPane('collection')` handler in `app.js`, alongside the existing `loadCollection()` and `loadCollectionStats()` calls. This matches the existing pattern where the pane-switch orchestrator fires parallel loads.

The fingerprint is **not** called inside `loadCollection()` to avoid re-fetching on refresh button clicks or post-sync reloads.

1. `_switchPane('collection')` calls `userPanes.loadTasteFingerprint()` in parallel with `loadCollection()` and `loadCollectionStats()`
2. `loadTasteFingerprint()` checks preconditions (auth + Discogs connected), then calls `apiClient.getTasteFingerprint(token)`
3. On success: render the strip into `#tasteStrip` via `_renderTasteStrip(data)`
4. On 422 / error: clear the `#tasteStrip` container

### Caching

Cache the fingerprint response in `_tasteCache`. Clear the cache on sync completion or Discogs disconnect. Subsequent pane switches reuse the cached data without re-fetching. No explicit cache TTL — it lasts for the browser session.

### Loading state

While the fingerprint is loading, show a subtle pulsing placeholder bar (same height as the rendered strip, ~120px) with a CSS animation. This prevents layout shift when the data arrives.

### On "Download Taste Card" click

1. Call `apiClient.getTasteCard(token)` — returns SVG blob
2. Create a blob URL and trigger download as `taste-card.svg`
3. Revoke the blob URL with `URL.revokeObjectURL()` after download triggers

## API Endpoints Consumed

| Endpoint | Method | When Called | Response Used |
|----------|--------|-------------|---------------|
| `/api/user/taste/fingerprint` | GET | Collection pane switch | `heatmap[]`, `obscurity{}`, `drift[]`, `blind_spots[]`, `peak_decade` |
| `/api/user/taste/card` | GET | Download button click | Raw SVG (`image/svg+xml`) |

Both require `Authorization: Bearer <jwt>` header.

The `peak_decade` field is an integer (e.g., `1990`). Display with an "s" suffix: `1990` → `"1990s"`.

## Files Modified

### `explore/static/js/api-client.js`

Add two methods to the `ApiClient` class:

- `getTasteFingerprint(token)` — GET `/api/user/taste/fingerprint` with auth header, returns JSON or null
- `getTasteCard(token)` — GET `/api/user/taste/card` with auth header, returns blob or null

### `explore/static/js/user-panes.js`

Add to the `UserPanes` class:

- `_tasteCache` — cached fingerprint response (null initially)
- `loadTasteFingerprint()` — checks preconditions, uses cache or fetches, renders into `#tasteStrip` by ID (matching the `_renderCollectionStats` pattern of looking up elements internally)
- `_renderTasteStrip(data)` — builds the 3-column dashboard strip DOM into `#tasteStrip`
- `_renderHeatmapGrid(cells)` — builds the genre x decade CSS grid from heatmap cells
- `_downloadTasteCard()` — fetches SVG blob and triggers browser download
- `clearTasteCache()` — called on sync or Discogs disconnect

### `explore/static/js/app.js`

Modify the `_switchPane('collection')` handler to call `userPanes.loadTasteFingerprint()` alongside `loadCollection()` and `loadCollectionStats()`.

### `explore/static/index.html`

Add `<div id="tasteStrip"></div>` inside `#collectionPane > .user-pane-body`, after `#collectionStats` and before `#collectionLoading`. Note: `#collectionLoading` is an absolutely-positioned overlay, so the taste strip's DOM position between stats and loading does not cause visual interference.

### `explore/static/css/styles.css`

Add styles for:
- `.taste-strip` — 3-column CSS grid, gap, background, border-radius
- `.taste-strip-loading` — pulsing placeholder animation
- `.taste-col` — individual column padding and flex layout
- `.taste-col-header` — small uppercase label (FINGERPRINT, HEATMAP, BLIND SPOTS)
- `.taste-stat` — key-value row for obscurity/peak/drift
- `.taste-stat-value` — large colored number using existing `--accent-purple`, `--accent-blue`, `--accent-green` CSS variables
- `.taste-heatmap-grid` — CSS grid for the heatmap cells
- `.taste-heatmap-cell` — individual cell with dynamic background opacity
- `.taste-blindspot-item` — blind spot list item
- `.taste-download-btn` — styled download button
- Responsive breakpoints at 1024px and 640px

## Heatmap Rendering

The heatmap cells from the API are `{genre, decade, count}`. To render:

1. Group cells by genre, sort genres by total count descending, take top 5
2. Collect unique decades, sort ascending
3. Render a CSS grid: first column = genre labels, remaining columns = decade headers + cells
4. Cell background: purple scale using `--accent-purple` CSS variable with opacity based on count relative to max count in the dataset
   - `opacity = count / maxCount` applied to the purple
   - Zero counts get `var(--bg-tertiary)` background

## Taste Drift Display

The drift array contains `{year, top_genre, count}` entries. To summarize in one line:
- Take first and last entries from the drift array
- Display as `"{first_genre} → {last_genre}"` if they differ
- Display as `"{genre} (consistent)"` if they're the same

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Not authenticated | Strip not rendered (loadTasteFingerprint skips) |
| Discogs not connected | Strip not rendered (loadTasteFingerprint skips) |
| 422 (< 10 collection items) | Strip hidden |
| 503 (service not ready) | Strip hidden |
| Network error | Strip hidden |
| Empty heatmap/drift/blindspots | Respective column shows "—" placeholder |

## Out of Scope

- Auto-refreshing the taste strip after completing Discogs OAuth (requires `authManager.notify()` listener changes). The strip will appear on next Collection pane switch after connecting.
- Frontend unit tests — the explore service has no frontend test infrastructure.

## Security

- All API calls include JWT auth header from `authManager.getToken()`
- SVG taste card is server-rendered with `html.escape()` for XSS prevention — no client-side SVG construction
- Download uses blob URL (no direct DOM insertion of SVG content)
- Blob URL revoked after download to prevent memory leaks
