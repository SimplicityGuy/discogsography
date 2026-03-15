# Taste Fingerprint UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a taste fingerprint dashboard strip to the Collection pane in the Explore UI, showing heatmap, obscurity, blind spots, and a downloadable taste card.

**Architecture:** Vanilla JS additions to the existing `ApiClient` and `UserPanes` classes, plus CSS styles and a container div in `index.html`. No new frameworks or dependencies. Single API call on pane switch, SVG download on demand.

**Tech Stack:** Vanilla JS, CSS Grid, existing CSS variables, Font Awesome icons.

**Spec:** `docs/superpowers/specs/2026-03-14-taste-fingerprint-ui-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `explore/static/css/styles.css` | Modify | Add CSS variables, taste strip styles, responsive breakpoints |
| `explore/static/js/api-client.js` | Modify | Add `getTasteFingerprint()` and `getTasteCard()` methods |
| `explore/static/js/user-panes.js` | Modify | Add taste loading, rendering, caching, and download logic |
| `explore/static/index.html` | Modify | Add `#tasteStrip` container div |
| `explore/static/js/app.js` | Modify | Wire `loadTasteFingerprint()` into `_switchPane('collection')` |

---

## Chunk 1: CSS + HTML Foundation

### Task 1: Add CSS variables and taste strip styles

**Files:**
- Modify: `explore/static/css/styles.css` (append to end of file)

- [ ] **Step 1: Add missing CSS variables to `:root`**

In `explore/static/css/styles.css`, add `--accent-purple` and `--bg-tertiary` to the existing `:root` block (after `--accent-red`):

```css
    --accent-purple: #6b46c1;
    --bg-tertiary: #2a2d45;
```

- [ ] **Step 2: Add taste strip styles**

Append to the end of `explore/static/css/styles.css`:

```css
/* ------------------------------------------------------------------ */
/* Taste Fingerprint Strip                                            */
/* ------------------------------------------------------------------ */

.taste-strip {
    display: grid;
    grid-template-columns: 1fr 1.5fr 1fr;
    gap: 12px;
    background: var(--bg-card);
    border: 1px solid var(--border-color, #2d3748);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 12px;
}

.taste-strip-loading {
    height: 120px;
    background: var(--bg-card);
    border: 1px solid var(--border-color, #2d3748);
    border-radius: 8px;
    margin-bottom: 12px;
    animation: taste-pulse 1.5s ease-in-out infinite;
}

@keyframes taste-pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 0.7; }
}

.taste-col {
    display: flex;
    flex-direction: column;
    padding: 4px;
}

.taste-col-header {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
    margin-bottom: 8px;
}

.taste-stat {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 6px;
}

.taste-stat-label {
    font-size: 12px;
    color: var(--text-secondary);
}

.taste-stat-value {
    font-weight: 700;
    font-size: 14px;
}

.taste-stat-value.purple { color: var(--accent-purple); }
.taste-stat-value.blue { color: var(--accent-blue); }
.taste-stat-value.green { color: var(--accent-green); }

.taste-heatmap-grid {
    display: grid;
    gap: 2px;
    font-size: 10px;
}

.taste-heatmap-label {
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    line-height: 18px;
}

.taste-heatmap-header {
    text-align: center;
    color: var(--text-secondary);
    font-size: 9px;
}

.taste-heatmap-cell {
    border-radius: 2px;
    height: 18px;
    min-width: 0;
}

.taste-blindspot-item {
    display: flex;
    justify-content: space-between;
    padding: 3px 0;
    border-bottom: 1px solid var(--border-color, #2d3748);
    font-size: 12px;
}

.taste-blindspot-item:last-child {
    border-bottom: none;
}

.taste-blindspot-name {
    color: var(--text-primary);
}

.taste-blindspot-count {
    color: var(--text-secondary);
    font-size: 11px;
}

.taste-download-btn {
    margin-top: auto;
    padding: 6px 12px;
    background: var(--accent-purple);
    color: #fff;
    border: none;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
    text-align: center;
    transition: opacity 0.15s;
}

.taste-download-btn:hover {
    opacity: 0.85;
}

.taste-download-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.taste-empty {
    color: var(--text-secondary);
    font-size: 12px;
}

/* Responsive: taste strip */
@media (max-width: 1024px) {
    .taste-strip {
        grid-template-columns: 1fr 1.5fr;
    }
    .taste-col:last-child {
        grid-column: 1 / -1;
    }
}

@media (max-width: 640px) {
    .taste-strip {
        grid-template-columns: 1fr;
    }
    .taste-col:last-child {
        grid-column: auto;
    }
}
```

- [ ] **Step 3: Commit CSS changes**

```bash
git add explore/static/css/styles.css
git commit -m "feat(explore): add taste fingerprint strip CSS styles (#129)"
```

### Task 2: Add HTML container

**Files:**
- Modify: `explore/static/index.html:554-558`

- [ ] **Step 1: Add `#tasteStrip` div**

In `explore/static/index.html`, inside the `#collectionPane > .user-pane-body` div, add a new div after `#collectionStats` and before `#collectionLoading`:

```html
                <div id="tasteStrip"></div>
```

The existing HTML at lines 554-560 looks like:

```html
        <div class="pane" id="collectionPane">
            <div class="user-pane-body">
                <div id="collectionStats"></div>
                <div id="tasteStrip"></div>          <!-- ADD THIS LINE -->
                <div class="loading-overlay" id="collectionLoading">
```

- [ ] **Step 2: Commit HTML change**

```bash
git add explore/static/index.html
git commit -m "feat(explore): add taste strip container to collection pane (#129)"
```

---

## Chunk 2: API Client Methods

### Task 3: Add taste API methods to ApiClient

**Files:**
- Modify: `explore/static/js/api-client.js` (add before the closing `}` of the class, after the `getSyncStatus` method)

- [ ] **Step 1: Add `getTasteFingerprint` method**

Add after the `getSyncStatus` method (line ~337) and before the closing `}` of the class:

```javascript

    // --- Taste fingerprint ---

    /**
     * Get full taste fingerprint (heatmap, obscurity, drift, blind spots).
     * @param {string} token - JWT auth token
     * @returns {Promise<Object|null>} Fingerprint data or null on error/422
     */
    async getTasteFingerprint(token) {
        if (!token) return null;
        const response = await fetch('/api/user/taste/fingerprint', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.json();
    }

    /**
     * Download SVG taste card.
     * @param {string} token - JWT auth token
     * @returns {Promise<Blob|null>} SVG blob or null on error
     */
    async getTasteCard(token) {
        if (!token) return null;
        const response = await fetch('/api/user/taste/card', {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!response.ok) return null;
        return response.blob();
    }
```

- [ ] **Step 2: Commit API client changes**

```bash
git add explore/static/js/api-client.js
git commit -m "feat(explore): add taste fingerprint and card API methods (#129)"
```

---

## Chunk 3: UserPanes Taste Rendering

### Task 4: Add taste fingerprint loading and rendering to UserPanes

**Files:**
- Modify: `explore/static/js/user-panes.js` (add new methods to the class)

- [ ] **Step 1: Add `_tasteCache` property**

In the `UserPanes` constructor (after `this._discogsOAuthState = null;` on line 14), add:

```javascript
        this._tasteCache = null;
```

- [ ] **Step 2: Add `loadTasteFingerprint` method**

Add after the `triggerSync` method's closing brace (after line 346) and before the gap analysis section comment:

```javascript

    // ------------------------------------------------------------------ //
    // Taste fingerprint strip
    // ------------------------------------------------------------------ //

    async loadTasteFingerprint() {
        const token = window.authManager.getToken();
        if (!token) return;
        const discogsStatus = window.authManager.getDiscogsStatus();
        if (!discogsStatus?.connected) return;

        const strip = document.getElementById('tasteStrip');
        if (!strip) return;

        // Use cache if available
        if (this._tasteCache) {
            this._renderTasteStrip(this._tasteCache);
            return;
        }

        // Show loading placeholder
        strip.replaceChildren();
        const loader = document.createElement('div');
        loader.className = 'taste-strip-loading';
        strip.appendChild(loader);

        try {
            const data = await window.apiClient.getTasteFingerprint(token);
            if (!data) {
                // 422 (< 10 items), 503, or error — hide strip
                strip.replaceChildren();
                return;
            }
            this._tasteCache = data;
            this._renderTasteStrip(data);
        } catch {
            strip.replaceChildren();
        }
    }

    clearTasteCache() {
        this._tasteCache = null;
    }
```

- [ ] **Step 3: Add `_renderTasteStrip` method**

Add immediately after `clearTasteCache`:

```javascript

    _renderTasteStrip(data) {
        const strip = document.getElementById('tasteStrip');
        if (!strip) return;
        strip.replaceChildren();

        const container = document.createElement('div');
        container.className = 'taste-strip';

        // Column 1: Fingerprint stats
        const col1 = document.createElement('div');
        col1.className = 'taste-col';
        const h1 = document.createElement('div');
        h1.className = 'taste-col-header';
        h1.textContent = 'Fingerprint';
        col1.appendChild(h1);

        // Obscurity
        col1.appendChild(this._tasteStat(
            'Obscurity',
            data.obscurity?.score != null ? data.obscurity.score.toFixed(2) : '—',
            'purple',
        ));

        // Peak decade
        const peakText = data.peak_decade != null ? `${data.peak_decade}s` : '—';
        col1.appendChild(this._tasteStat('Peak', peakText, 'blue'));

        // Taste drift
        const driftText = this._formatDrift(data.drift);
        col1.appendChild(this._tasteStat('Drift', driftText, 'green'));

        container.appendChild(col1);

        // Column 2: Heatmap
        const col2 = document.createElement('div');
        col2.className = 'taste-col';
        const h2 = document.createElement('div');
        h2.className = 'taste-col-header';
        h2.textContent = 'Heatmap';
        col2.appendChild(h2);

        if (data.heatmap && data.heatmap.length > 0) {
            col2.appendChild(this._renderHeatmapGrid(data.heatmap));
        } else {
            const empty = document.createElement('div');
            empty.className = 'taste-empty';
            empty.textContent = '—';
            col2.appendChild(empty);
        }

        container.appendChild(col2);

        // Column 3: Blind spots + download
        const col3 = document.createElement('div');
        col3.className = 'taste-col';
        const h3 = document.createElement('div');
        h3.className = 'taste-col-header';
        h3.textContent = 'Blind Spots';
        col3.appendChild(h3);

        if (data.blind_spots && data.blind_spots.length > 0) {
            data.blind_spots.forEach(spot => {
                const item = document.createElement('div');
                item.className = 'taste-blindspot-item';
                const name = document.createElement('span');
                name.className = 'taste-blindspot-name';
                name.textContent = spot.genre;
                const count = document.createElement('span');
                count.className = 'taste-blindspot-count';
                count.textContent = `${spot.artist_overlap} artists`;
                item.append(name, count);
                col3.appendChild(item);
            });
        } else {
            const empty = document.createElement('div');
            empty.className = 'taste-empty';
            empty.textContent = 'No blind spots found';
            col3.appendChild(empty);
        }

        // Download button
        const dlBtn = document.createElement('button');
        dlBtn.className = 'taste-download-btn';
        const dlIcon = document.createElement('i');
        dlIcon.className = 'fas fa-download mr-1';
        dlBtn.append(dlIcon, 'Download Taste Card');
        dlBtn.addEventListener('click', () => this._downloadTasteCard(dlBtn));
        col3.appendChild(dlBtn);

        container.appendChild(col3);
        strip.appendChild(container);
    }
```

- [ ] **Step 4: Add helper methods**

Add immediately after `_renderTasteStrip`:

```javascript

    _tasteStat(label, value, colorClass) {
        const row = document.createElement('div');
        row.className = 'taste-stat';
        const labelEl = document.createElement('span');
        labelEl.className = 'taste-stat-label';
        labelEl.textContent = label;
        const valueEl = document.createElement('span');
        valueEl.className = `taste-stat-value ${colorClass}`;
        valueEl.textContent = value;
        row.append(labelEl, valueEl);
        return row;
    }

    _formatDrift(drift) {
        if (!drift || drift.length === 0) return '—';
        const first = drift[0].top_genre;
        const last = drift[drift.length - 1].top_genre;
        if (first === last) return `${first} (consistent)`;
        return `${first} → ${last}`;
    }

    _renderHeatmapGrid(cells) {
        // Group by genre, sort by total count desc, take top 5
        const genreTotals = {};
        let maxCount = 0;
        cells.forEach(c => {
            genreTotals[c.genre] = (genreTotals[c.genre] || 0) + c.count;
            if (c.count > maxCount) maxCount = c.count;
        });
        const topGenres = Object.entries(genreTotals)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(e => e[0]);

        // Collect unique decades, sorted
        const decades = [...new Set(cells.map(c => c.decade))].sort((a, b) => a - b);

        // Build lookup: genre+decade -> count
        const lookup = {};
        cells.forEach(c => { lookup[`${c.genre}-${c.decade}`] = c.count; });

        // CSS grid: first col = genre label, rest = decade columns
        const grid = document.createElement('div');
        grid.className = 'taste-heatmap-grid';
        grid.style.gridTemplateColumns = `60px repeat(${decades.length}, 1fr)`;

        // Header row
        const corner = document.createElement('div');
        grid.appendChild(corner);
        decades.forEach(d => {
            const hdr = document.createElement('div');
            hdr.className = 'taste-heatmap-header';
            hdr.textContent = `${d}s`;
            grid.appendChild(hdr);
        });

        // Data rows
        topGenres.forEach(genre => {
            const label = document.createElement('div');
            label.className = 'taste-heatmap-label';
            label.textContent = genre;
            label.title = genre;
            grid.appendChild(label);

            decades.forEach(decade => {
                const count = lookup[`${genre}-${decade}`] || 0;
                const cell = document.createElement('div');
                cell.className = 'taste-heatmap-cell';
                const opacity = maxCount > 0 ? count / maxCount : 0;
                if (count === 0) {
                    cell.style.background = 'var(--bg-tertiary)';
                } else {
                    cell.style.background = `rgba(107, 70, 193, ${Math.max(0.15, opacity)})`;
                }
                cell.title = `${genre} ${decade}s: ${count}`;
                grid.appendChild(cell);
            });
        });

        return grid;
    }

    async _downloadTasteCard(btn) {
        const token = window.authManager.getToken();
        if (!token) return;

        const resetBtn = () => {
            btn.disabled = false;
            btn.replaceChildren();
            const icon = document.createElement('i');
            icon.className = 'fas fa-download mr-1';
            btn.append(icon, 'Download Taste Card');
        };

        btn.disabled = true;
        btn.textContent = 'Downloading...';

        const blob = await window.apiClient.getTasteCard(token);
        if (!blob) {
            btn.textContent = 'Download failed';
            setTimeout(resetBtn, 2000);
            return;
        }

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'taste-card.svg';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        resetBtn();
    }
```

- [ ] **Step 5: Clear taste cache on sync and disconnect**

In the `triggerSync` method, inside the `setTimeout` callback that reloads collection/wantlist (around line 337-339), add the taste cache clear and reload alongside the existing reloads:

```javascript
                    this.clearTasteCache();
                    this.loadTasteFingerprint();
```

These go inside the `setTimeout(() => { ... }, 2000)` block, after `this.loadWantlist(true);`, so the taste data is re-fetched after the sync has had time to start processing.

In the `disconnectDiscogs` method, before the `window.authManager.notify()` call (around line 318), add:

```javascript
        this.clearTasteCache();
```

- [ ] **Step 6: Commit UserPanes changes**

```bash
git add explore/static/js/user-panes.js
git commit -m "feat(explore): add taste fingerprint strip rendering to UserPanes (#129)"
```

---

## Chunk 4: Wire Up and Verify

### Task 5: Wire taste loading into pane switch

**Files:**
- Modify: `explore/static/js/app.js:482-484`

- [ ] **Step 1: Add `loadTasteFingerprint` call to `_switchPane`**

In `explore/static/js/app.js`, find the `_switchPane` method's collection branch (around line 482):

```javascript
        } else if (pane === 'collection' && window.authManager.isLoggedIn()) {
            this.userPanes.loadCollection(true);
            this.userPanes.loadCollectionStats();
```

Add the taste fingerprint call:

```javascript
        } else if (pane === 'collection' && window.authManager.isLoggedIn()) {
            this.userPanes.loadCollection(true);
            this.userPanes.loadCollectionStats();
            this.userPanes.loadTasteFingerprint();
```

- [ ] **Step 2: Commit app.js change**

```bash
git add explore/static/js/app.js
git commit -m "feat(explore): wire taste fingerprint into collection pane switch (#129)"
```

### Task 6: Manual verification

- [ ] **Step 1: Verify all files are saved and committed**

```bash
git status
git log --oneline -6
```

Expected: clean working tree, 5 new commits (CSS, HTML, API client, UserPanes, app.js wiring).

- [ ] **Step 2: Visual verification checklist**

Verify the following by inspecting the code (no live server needed since PR #120 isn't merged yet):

1. `api-client.js` — `getTasteFingerprint` returns JSON, `getTasteCard` returns blob
2. `user-panes.js` — precondition checks for token + Discogs connected
3. `user-panes.js` — cache used on subsequent loads, cleared on sync/disconnect
4. `user-panes.js` — loading placeholder shown, replaced on success or hidden on error
5. `user-panes.js` — blob URL revoked after download
6. `styles.css` — responsive breakpoints at 1024px and 640px
7. `index.html` — `#tasteStrip` positioned between `#collectionStats` and `#collectionLoading`
8. `app.js` — `loadTasteFingerprint()` called alongside existing loads, not inside `loadCollection()`
