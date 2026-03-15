# Vinyl Archaeology — Time-Travel Through the Knowledge Graph

**Issue**: #113
**Date**: 2026-03-14
**Status**: Approved

## Overview

Add a year-based time filter to the graph exploration UI, letting users scrub through decades and watch the music world assemble itself. Uses existing `Release.year` property (indexed via `release_year_index`) — no new data ingestion required.

## Scope

**In scope (this PR):**

1. `before_year` query parameter on `/api/expand`
2. `/api/explore/year-range` endpoint (slider bounds)
3. `/api/explore/genre-emergence` endpoint (first-appearance years)
4. Timeline scrubber UI component (slider + play/pause + speed toggle)
5. Genre emergence highlights in the graph
6. Tests (unit + E2E, ≥80% coverage)

**Deferred (follow-up issue):**

- Snapshot comparison — pin two years side-by-side to compare graph state

## Backend Design

### Parameter Threading

All `expand_*` and `count_*` functions in `api/queries/neo4j_queries.py` gain:

```python
before_year: int | None = None
```

Both expand and count functions must apply the same year filter so that `total` and `has_more` in the `/api/expand` response remain consistent with filtered results.

`before_year` is passed as a keyword argument at call sites to avoid breaking positional signatures:
```python
query_func(driver, node_id, limit, offset, before_year=before_year)
```

Filtering logic by query type:

| Query type | Filter applied |
|-----------|---------------|
| Release-direct (e.g. `expand_artist_releases`) | `AND r.year <= $before_year AND r.year > 0` |
| Transitive (e.g. `expand_artist_labels`) | Filter intermediate Release node |
| Non-release (aliases, members) | No filter — timeless relationships |

### New Endpoints

**`GET /api/explore/year-range`**

Returns min/max year across all Release nodes. Called once on entity load, result cached client-side for the session (deterministic until graph changes).

```json
{"min_year": 1950, "max_year": 2025}
```

Cypher:
```cypher
MATCH (r:Release) WHERE r.year > 0
RETURN min(r.year) AS min_year, max(r.year) AS max_year
```

**`GET /api/explore/genre-emergence?before_year=YYYY`**

Returns all genres and styles whose first release appeared on or before `before_year`, along with that first-appearance year. The frontend diffs consecutive responses client-side to determine which genres are "new" at the current slider position.

```json
{
  "genres": [{"name": "Punk", "first_year": 1976}, ...],
  "styles": [{"name": "Post-Punk", "first_year": 1978}, ...]
}
```

The frontend caches responses by `before_year` value to avoid redundant queries during play mode.

### Router Changes

`api/routers/explore.py`:
- `/api/expand` gains `before_year: int | None = Query(default=None, ge=1900, le=2030)`
- Two new route functions for year-range and genre-emergence

### Category Count Consistency

`/api/explore` returns category counts (e.g. "Releases: 147"). These counts are **not** year-filtered — they always reflect the full graph. The timeline scrubber shows a separate "Showing N of M" indicator per category when `before_year` is active, using the filtered total from `/api/expand` responses.

### Dispatch Table Updates

`EXPAND_DISPATCH` and `COUNT_DISPATCH` callers pass `before_year` through as a keyword argument. The dispatch functions themselves gain the parameter.

## Frontend Design

### Timeline Scrubber Component

Location: Below graph container, above trends pane in `index.html`.

Elements:
- Year label showing current filter value
- Native HTML range input (min/max from `/api/explore/year-range`)
- Play/pause button
- Speed toggle: 1 year/second or 1 decade/500ms

Styled with Tailwind dark theme, consistent with existing UI. Hidden until an entity is loaded.

### Interaction Flow

1. Entity loaded → call `/api/explore/year-range` (cached) → set slider bounds
2. Slider defaults to max year (full graph, no filtering)
3. Slider drag → debounced (300ms) re-fetch of expanded categories with `before_year`
4. Play → `setInterval` advances slider, each tick cancels any in-flight request before issuing the next (no debounce in play mode — direct fetch per tick)
5. Dragging the slider while play is active pauses playback and resumes manual control
6. Genre emergence: frontend diffs previous/current genre-emergence responses. Newly-appearing genres get CSS glow highlight + "NEW" badge (fades after 2s). On large year jumps (>5 years), only the 5 most recent emergences are highlighted to avoid visual clutter.
7. Empty categories: when `before_year` filters out all results for a category, the category pill shows "0" and is greyed out (not hidden, so the user sees the structure)

### File Changes

| File | Changes |
|------|---------|
| `api-client.js` | `expand()` accepts `beforeYear`, new `getYearRange()` and `getGenreEmergence()` |
| `graph.js` | `setBeforeYear(year)` clears/re-fetches categories, emergence highlight class |
| `app.js` | New `TimelineScrubber` controller (slider state, play/pause, graph coordination) |
| `index.html` | Timeline bar markup + emergence highlight CSS |

No new JS dependencies.

## Testing

### Backend Tests

- `test_neo4j_queries.py`: Each modified `expand_*`/`count_*` with and without `before_year` — verify Cypher includes year filter when set, omits when `None`
- `test_explore.py`: `/api/expand?before_year=1980`, `/api/explore/year-range`, `/api/explore/genre-emergence`
- Validation: `before_year` outside 1900-2030 returns 422

### Frontend Tests

- `test_explore_ui.py`: Timeline scrubber appears after entity load, slider triggers API calls with `before_year`, play/pause works

### Coverage

≥80% on all new code.
