# Snapshot Comparison Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add snapshot comparison to Vinyl Archaeology — pin two years via a dual range slider and see a color-coded overlay diff on the graph.

**Architecture:** Client-side only. The `TimelineScrubber` class gains a compare mode with two sliders. `GraphVisualization` gets `setCompareYears()`/`clearComparison()` methods that fetch two expand results per category and diff them using set operations on composite node keys (`type:id`). Nodes are styled by `compareStatus` — "both", "only_a", "only_b".

**Tech Stack:** Vanilla JS, D3.js, existing `/api/expand?before_year=` endpoint

**Spec:** `docs/superpowers/specs/2026-03-15-snapshot-comparison-design.md`

---

## Chunk 1: HTML/CSS Foundation

### Task 1: Add Compare Toggle and Dual Slider HTML

**Files:**
- Modify: `explore/static/index.html:466-480`

- [ ] **Step 1: Add compare toggle button and dual slider markup**

Replace the timeline scrubber HTML (lines 466-480) with:

```html
<div class="timeline-scrubber hidden" id="timelineScrubber">
    <div class="timeline-controls" id="timelineExploreControls">
        <button class="timeline-btn" id="timelinePlayBtn" title="Play/Pause">
            <span class="material-symbols-outlined" id="timelinePlayIcon">play_arrow</span>
        </button>
        <span class="timeline-year" id="timelineYearLabel">—</span>
        <input type="range" class="timeline-slider" id="timelineSlider" min="1900" max="2025" value="2025" />
        <div class="timeline-speed" id="timelineSpeedToggle" title="Toggle speed">
            <span id="timelineSpeedLabel">1yr/s</span>
        </div>
        <button class="timeline-btn" id="timelineResetBtn" title="Reset (show all years)">
            <span class="material-symbols-outlined">undo</span>
        </button>
        <button class="timeline-btn" id="timelineCompareBtn" title="Compare two years">
            <span class="material-symbols-outlined">compare_arrows</span>
        </button>
    </div>
    <div class="timeline-controls hidden" id="timelineCompareControls">
        <span class="timeline-year timeline-year-a" id="compareYearALabel">1975</span>
        <input type="range" class="timeline-slider timeline-slider-a" id="compareSliderA" min="1900" max="2025" value="1975" />
        <span class="timeline-compare-arrow">↔</span>
        <input type="range" class="timeline-slider timeline-slider-b" id="compareSliderB" min="1900" max="2025" value="1995" />
        <span class="timeline-year timeline-year-b" id="compareYearBLabel">1995</span>
        <button class="timeline-btn" id="timelineExitCompareBtn" title="Exit comparison">
            <span class="material-symbols-outlined">close</span>
        </button>
    </div>
</div>
```

- [ ] **Step 2: Add comparison legend markup**

Insert after the timeline scrubber div (after line 480), before the closing `</div>` of the graph pane:

```html
<div class="compare-legend hidden" id="compareLegend">
    <button class="compare-legend-close" id="compareLegendClose" title="Hide legend">
        <span class="material-symbols-outlined" style="font-size:14px">close</span>
    </button>
    <div class="compare-legend-item">
        <span class="compare-legend-swatch compare-swatch-both"></span>
        <span>Both years</span>
    </div>
    <div class="compare-legend-item">
        <span class="compare-legend-swatch compare-swatch-only-a"></span>
        <span>Year A only</span>
    </div>
    <div class="compare-legend-item">
        <span class="compare-legend-swatch compare-swatch-only-b"></span>
        <span>Year B only</span>
    </div>
</div>
```

- [ ] **Step 3: Verify the HTML renders** — open the Explore page in a browser and confirm the compare button appears in the timeline bar (it won't do anything yet).

- [ ] **Step 4: Commit**

```bash
git add explore/static/index.html
git commit -m "feat(explore): add compare toggle and dual slider HTML for snapshot comparison (#126)"
```

### Task 2: Add Comparison CSS

**Files:**
- Modify: `explore/static/index.html:21-89` (inline `<style>` block)

- [ ] **Step 1: Add comparison CSS styles**

Append these styles after the `.emergence-badge` rule (before the closing `</style>` on line 89):

```css
/* Comparison mode */
.timeline-compare-arrow {
    font-size: 1.2rem;
    color: var(--text-mid);
    user-select: none;
}
.timeline-year-a { color: #818cf8; }
.timeline-year-b { color: #a78bfa; }
.timeline-slider-a { accent-color: #4f46e5; }
.timeline-slider-b { accent-color: #7c3aed; }
.timeline-btn.active {
    background: var(--purple-accent);
    color: #fff;
    border-color: var(--purple-accent);
}

/* Comparison legend */
.compare-legend {
    position: absolute;
    bottom: 56px;
    left: 12px;
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 0.75rem;
    color: var(--text-mid);
    z-index: 10;
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.compare-legend.hidden { display: none; }
.compare-legend-close {
    position: absolute;
    top: 4px;
    right: 4px;
    background: none;
    border: none;
    color: var(--text-mid);
    cursor: pointer;
    padding: 0;
    line-height: 1;
}
.compare-legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
}
.compare-legend-swatch {
    display: inline-block;
    width: 12px;
    height: 12px;
    border-radius: 50%;
}
.compare-swatch-both {
    background: #6366f1;
    border: 2px solid rgba(255,255,255,0.3);
}
.compare-swatch-only-a {
    background: rgba(79,70,229,0.4);
    border: 2px dashed #818cf8;
}
.compare-swatch-only-b {
    background: #059669;
    border: 2px solid #34d399;
}

/* Comparison node/link styles */
.link-only-a {
    stroke-dasharray: 4 2;
    opacity: 0.4;
}
.link-only-b {
    stroke: #34d399;
}

/* Same-year hint */
.compare-same-year-hint {
    position: absolute;
    bottom: 56px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 0.8rem;
    color: var(--text-mid);
    z-index: 10;
    white-space: nowrap;
}
.compare-same-year-hint.hidden { display: none; }
```

- [ ] **Step 2: Add the same-year hint element to HTML**

Insert after the compare legend div:

```html
<div class="compare-same-year-hint hidden" id="compareSameYearHint">
    Select different years to compare
</div>
```

- [ ] **Step 3: Verify styles render** — open browser, inspect that legend/slider CSS variables resolve correctly in both light and dark themes.

- [ ] **Step 4: Commit**

```bash
git add explore/static/index.html
git commit -m "feat(explore): add comparison CSS for overlay diff styling (#126)"
```

## Chunk 2: TimelineScrubber Compare Mode

### Task 3: Add Compare Mode to TimelineScrubber

**Files:**
- Modify: `explore/static/js/app.js:1-165` (TimelineScrubber class)

- [ ] **Step 1: Add compare state properties**

In the constructor (after line 27, after `this._previousGenres = new Set();`), add:

```javascript
// Compare mode state
this.comparing = false;
this._savedBeforeYear = null;
this.compareYearA = null;
this.compareYearB = null;

// Compare mode DOM references
this.exploreControls = document.getElementById('timelineExploreControls');
this.compareControls = document.getElementById('timelineCompareControls');
this.compareBtn = document.getElementById('timelineCompareBtn');
this.exitCompareBtn = document.getElementById('timelineExitCompareBtn');
this.sliderA = document.getElementById('compareSliderA');
this.sliderB = document.getElementById('compareSliderB');
this.yearALabel = document.getElementById('compareYearALabel');
this.yearBLabel = document.getElementById('compareYearBLabel');
this.compareLegend = document.getElementById('compareLegend');
this.legendCloseBtn = document.getElementById('compareLegendClose');
this.sameYearHint = document.getElementById('compareSameYearHint');

// Callback: called with (yearA, yearB) when comparison years change
this.onCompareChange = null;
// Callback: called with no args when comparison mode exits
this.onCompareExit = null;

// Debounce timer for compare slider drags
this._compareDebounceTimer = null;
```

- [ ] **Step 2: Add compare event bindings**

In `_bindEvents()` (after the `resetBtn` listener, before the closing `}`), add:

```javascript
this.compareBtn.addEventListener('click', () => this.enterCompare());
this.exitCompareBtn.addEventListener('click', () => this.exitCompare());

this.sliderA.addEventListener('input', () => this._onCompareSliderInput());
this.sliderB.addEventListener('input', () => this._onCompareSliderInput());

this.legendCloseBtn.addEventListener('click', () => {
    this.compareLegend.classList.add('hidden');
});
```

- [ ] **Step 3: Add compare mode methods**

After the `_checkEmergence` method (after line 164), add:

```javascript
enterCompare() {
    if (this.comparing) return;
    this.pause();
    this.comparing = true;

    // Save current single-slider state
    this._savedBeforeYear = this.currentYear;

    // Initialize compare sliders to sensible defaults
    const midYear = Math.floor((this.minYear + this.maxYear) / 2);
    this.compareYearA = this.currentYear ? Math.max(this.minYear, this.currentYear - 10) : midYear - 10;
    this.compareYearB = this.currentYear || midYear + 10;

    // Clamp to bounds
    this.compareYearA = Math.max(this.minYear, Math.min(this.maxYear, this.compareYearA));
    this.compareYearB = Math.max(this.minYear, Math.min(this.maxYear, this.compareYearB));

    this.sliderA.min = this.minYear;
    this.sliderA.max = this.maxYear;
    this.sliderA.value = this.compareYearA;
    this.sliderB.min = this.minYear;
    this.sliderB.max = this.maxYear;
    this.sliderB.value = this.compareYearB;
    this.yearALabel.textContent = String(this.compareYearA);
    this.yearBLabel.textContent = String(this.compareYearB);

    // Disable explore-only controls
    this.playBtn.disabled = true;
    this.playBtn.style.opacity = '0.4';
    this.speedToggle.style.opacity = '0.4';
    this.speedToggle.style.pointerEvents = 'none';

    // Toggle UI
    this.exploreControls.classList.add('hidden');
    this.compareControls.classList.remove('hidden');
    this.compareBtn.classList.add('active');
    this.compareLegend.classList.remove('hidden');
    this.sameYearHint.classList.add('hidden');

    this._emitCompareChange();
}

exitCompare() {
    if (!this.comparing) return;
    this.comparing = false;

    // Re-enable explore controls
    this.playBtn.disabled = false;
    this.playBtn.style.opacity = '';
    this.speedToggle.style.opacity = '';
    this.speedToggle.style.pointerEvents = '';

    // Toggle UI back
    this.compareControls.classList.add('hidden');
    this.exploreControls.classList.remove('hidden');
    this.compareBtn.classList.remove('active');
    this.compareLegend.classList.add('hidden');
    this.sameYearHint.classList.add('hidden');

    clearTimeout(this._compareDebounceTimer);

    // Restore previous single-slider state
    if (this._savedBeforeYear !== null) {
        this.currentYear = this._savedBeforeYear;
        this.slider.value = this._savedBeforeYear;
        this.yearLabel.textContent = String(this._savedBeforeYear);
    } else {
        this.currentYear = null;
        this.slider.value = this.maxYear;
        this.yearLabel.textContent = 'All';
    }
    this._savedBeforeYear = null;

    if (this.onCompareExit) this.onCompareExit();
}

_onCompareSliderInput() {
    this.compareYearA = parseInt(this.sliderA.value, 10);
    this.compareYearB = parseInt(this.sliderB.value, 10);
    this.yearALabel.textContent = String(this.compareYearA);
    this.yearBLabel.textContent = String(this.compareYearB);

    clearTimeout(this._compareDebounceTimer);
    this._compareDebounceTimer = setTimeout(() => {
        this._emitCompareChange();
    }, 300);
}

_emitCompareChange() {
    // Normalize: yearA = min, yearB = max
    const a = Math.min(this.compareYearA, this.compareYearB);
    const b = Math.max(this.compareYearA, this.compareYearB);

    if (a === b) {
        this.sameYearHint.classList.remove('hidden');
        this.compareLegend.classList.add('hidden');
    } else {
        this.sameYearHint.classList.add('hidden');
        this.compareLegend.classList.remove('hidden');
    }

    if (this.onCompareChange) this.onCompareChange(a, b);
}
```

- [ ] **Step 4: Update `init()` to set compare slider bounds**

In the `init()` method, after `this.slider.max = this.maxYear;` (line 70), add:

```javascript
this.sliderA.min = this.minYear;
this.sliderA.max = this.maxYear;
this.sliderB.min = this.minYear;
this.sliderB.max = this.maxYear;
```

- [ ] **Step 5: Update `hide()` to exit compare mode**

In the `hide()` method (line 79), add before `this.container.classList.add('hidden');`:

```javascript
if (this.comparing) this.exitCompare();
```

- [ ] **Step 6: Verify** — open browser, click the compare button. Explore controls should hide, compare sliders should appear with two year labels and a close button. Clicking close should restore the single slider.

- [ ] **Step 7: Commit**

```bash
git add explore/static/js/app.js
git commit -m "feat(explore): add compare mode to TimelineScrubber (#126)"
```

## Chunk 3: Graph Comparison Logic

### Task 4: Add Comparison Methods to GraphVisualization

**Files:**
- Modify: `explore/static/js/graph.js` (append new methods)

- [ ] **Step 1: Add compare state properties**

In the constructor (after `this.beforeYear = null;` on line 31), add:

```javascript
// Comparison mode state
this.compareMode = false;
this.compareYearA = null;
this.compareYearB = null;
```

- [ ] **Step 2: Add `setCompareYears()` method**

After the `_expandCategoryFiltered` method (after line 650), add:

```javascript
/**
 * Enter comparison mode: fetch data for two years and render overlay diff.
 * @param {number} yearA - Earlier year
 * @param {number} yearB - Later year
 */
async setCompareYears(yearA, yearB) {
    this.compareMode = true;
    this.compareYearA = yearA;
    this.compareYearB = yearB;
    this.beforeYear = null; // Compare mode uses its own state

    if (!this.centerName || !this.centerType) return;

    // Collect categories to compare
    const categories = [];
    for (const [catId, meta] of this._categoryMeta.entries()) {
        categories.push({ catId, ...meta });
    }

    if (categories.length === 0) return;

    // Clear child nodes, keep center and category nodes
    this.nodes = this.nodes.filter(n => n.isCenter || n.isCategory);
    this.links = this.links.filter(l => {
        const srcId = typeof l.source === 'object' ? l.source.id : l.source;
        const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
        const srcNode = this.nodes.find(n => n.id === srcId);
        const tgtNode = this.nodes.find(n => n.id === tgtId);
        return srcNode && tgtNode;
    });

    this.expandedCategories.clear();

    // Fetch and diff each category
    this._pendingExpands = categories.length;
    for (const cat of categories) {
        this._fetchComparisonData(cat.catId, cat.parentName, cat.parentType, cat.category);
    }
}

/**
 * Fetch data for both years and diff, then insert merged nodes.
 */
async _fetchComparisonData(categoryId, parentName, parentType, category) {
    this.expandedCategories.add(categoryId);
    try {
        // Parallel fetch for both years
        let dataA, dataB;
        try {
            [dataA, dataB] = await Promise.all([
                window.apiClient.expand(parentName, parentType, category, 30, 0, this.compareYearA),
                window.apiClient.expand(parentName, parentType, category, 30, 0, this.compareYearB),
            ]);
        } catch {
            // Show toast and abort — the caller will fall back to single-year mode
            const toast = document.getElementById('shareToast');
            const msg = document.getElementById('shareToastMsg');
            if (toast && msg) {
                msg.textContent = 'Comparison failed — falling back to single year';
                toast.classList.add('show');
                setTimeout(() => toast.classList.remove('show'), 3000);
            }
            return;
        }

        // Build lookup maps keyed by composite type:id
        const mapA = new Map();
        for (const child of dataA.children) {
            mapA.set(`${child.type}:${child.id}`, child);
        }
        const mapB = new Map();
        for (const child of dataB.children) {
            mapB.set(`${child.type}:${child.id}`, child);
        }

        // Compute diff sets
        const allKeys = new Set([...mapA.keys(), ...mapB.keys()]);

        // Update category label with diff counts
        const catNode = this.nodes.find(n => n.id === categoryId);
        if (catNode) {
            catNode.name = `${catNode.displayName} (${dataA.total} → ${dataB.total})`;
            catNode.count = dataB.total;
        }

        // Store pagination metadata (use yearB totals for display)
        this._categoryMeta.set(categoryId, {
            parentName, parentType, category,
            offset: allKeys.size, limit: 30, total: dataB.total,
        });

        for (const key of allKeys) {
            const inA = mapA.has(key);
            const inB = mapB.has(key);
            const child = inB ? mapB.get(key) : mapA.get(key);
            const childId = `child-${child.type}-${child.id}`;

            if (this.nodes.find(n => n.id === childId)) continue;

            const compareStatus = (inA && inB) ? 'both' : inA ? 'only_a' : 'only_b';

            this.nodes.push({
                id: childId,
                name: child.name,
                type: child.type,
                isCenter: false,
                isCategory: false,
                nodeId: String(child.id),
                compareStatus,
            });
            this.links.push({
                source: categoryId,
                target: childId,
                compareStatus,
            });
        }

        // No load-more in comparison mode
    } finally {
        this._pendingExpands--;
        this._checkExpandsDone();
    }
}

/**
 * Exit comparison mode and restore single-year view.
 */
clearComparison() {
    this.compareMode = false;
    this.compareYearA = null;
    this.compareYearB = null;

    // Strip compareStatus from nodes/links
    for (const node of this.nodes) {
        delete node.compareStatus;
    }
    for (const link of this.links) {
        delete link.compareStatus;
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add explore/static/js/graph.js
git commit -m "feat(explore): add setCompareYears/clearComparison to GraphVisualization (#126)"
```

### Task 5: Add Comparison Node and Link Styling to Render

**Files:**
- Modify: `explore/static/js/graph.js:385-459` (`_render()` method)

- [ ] **Step 1: Add comparison styling to node shapes**

In the `_render()` method, inside `node.each(function(d) { ... })` (line 385-424), replace the `else` block (lines 413-423) that handles regular circle nodes with:

```javascript
} else {
    const circle = el.append('circle')
        .attr('r', radius)
        .attr('fill', d.isCenter ? 'var(--node-' + d.type + ')' :
            d.type === 'artist' ? 'var(--node-artist)' :
            d.type === 'release' ? 'var(--node-release)' :
            d.type === 'label' ? 'var(--node-label)' :
            d.type === 'genre' || d.type === 'style' ? 'var(--node-genre)' : '#888')
        .attr('stroke', d.isCenter ? '#fff' : 'rgba(255,255,255,0.3)')
        .attr('stroke-width', d.isCenter ? 3 : 1);

    // Comparison mode styling
    if (d.compareStatus === 'only_a') {
        circle
            .attr('opacity', 0.4)
            .attr('stroke', '#818cf8')
            .attr('stroke-width', 2)
            .attr('stroke-dasharray', '4 2');
    } else if (d.compareStatus === 'only_b') {
        circle
            .attr('stroke', '#34d399')
            .attr('stroke-width', 2.5)
            .attr('filter', 'drop-shadow(0 0 4px #059669)');
    }
}
```

- [ ] **Step 2: Add comparison styling to links**

In the `_render()` method, where links are created (lines 364-369), replace:

```javascript
const link = this.g.append('g')
    .selectAll('line')
    .data(this.links)
    .join('line')
    .attr('class', 'link')
    .attr('stroke-width', 1);
```

with:

```javascript
const link = this.g.append('g')
    .selectAll('line')
    .data(this.links)
    .join('line')
    .attr('class', d => {
        let cls = 'link';
        if (d.compareStatus === 'only_a') cls += ' link-only-a';
        else if (d.compareStatus === 'only_b') cls += ' link-only-b';
        return cls;
    })
    .attr('stroke-width', 1);
```

- [ ] **Step 3: Add comparison status to tooltips**

In the tooltip section (line 427-435), replace:

```javascript
node.append('title').text(d => {
    if (d.isCenter) return `${d.name} [${d.type}]`;
    if (d.isCategory) return `${d.displayName || d.name}\n${d.count || 0} items`;
    if (d.isLoadMore) return `${d.name}\nClick to load more`;
    const explorableTypes = ['artist', 'genre', 'label', 'style'];
    const hints = ['Click for details'];
    if (explorableTypes.includes(d.type)) hints.push('double-click to explore');
    return `${d.name} [${d.type}]\n${hints.join(', ')}`;
});
```

with:

```javascript
node.append('title').text(d => {
    if (d.isCenter) return `${d.name} [${d.type}]`;
    if (d.isCategory) return `${d.displayName || d.name}\n${d.count || 0} items`;
    if (d.isLoadMore) return `${d.name}\nClick to load more`;
    const explorableTypes = ['artist', 'genre', 'label', 'style'];
    const hints = ['Click for details'];
    if (explorableTypes.includes(d.type)) hints.push('double-click to explore');
    let suffix = '';
    if (d.compareStatus === 'only_a') suffix = '\n(Year A only)';
    else if (d.compareStatus === 'only_b') suffix = '\n(Year B only)';
    return `${d.name} [${d.type}]\n${hints.join(', ')}${suffix}`;
});
```

- [ ] **Step 4: Verify** — open browser, explore an entity, enter compare mode, drag sliders. Nodes should appear with diff styling. Category labels should show "N → M" format.

- [ ] **Step 5: Commit**

```bash
git add explore/static/js/graph.js
git commit -m "feat(explore): add comparison node/link styling to graph render (#126)"
```

## Chunk 4: App Integration and Wiring

### Task 6: Wire Compare Mode in ExploreApp

**Files:**
- Modify: `explore/static/js/app.js:580-605` (ExploreApp callbacks)

- [ ] **Step 1: Connect compare callbacks**

In the ExploreApp class, find where the timeline callbacks are set up (should be in the constructor or init area where `this.timeline.onYearChange` is assigned). Add after those assignments:

```javascript
this.timeline.onCompareChange = (yearA, yearB) => this._onCompareChange(yearA, yearB);
this.timeline.onCompareExit = () => this._onCompareExit();
```

- [ ] **Step 2: Add compare handler methods**

After the `_onGenreEmergence` method (after line 605), add:

```javascript
_onCompareChange(yearA, yearB) {
    if (yearA === yearB) {
        // Same year — clear comparison styling, show as single year
        this.graph.clearComparison();
        this.graph.setBeforeYear(yearA);
        return;
    }
    this.graph.setCompareYears(yearA, yearB);
}

_onCompareExit() {
    this.graph.clearComparison();
    // Re-fetch with the restored single-year filter
    this.graph.setBeforeYear(this.timeline.currentYear);
}
```

- [ ] **Step 3: Verify full flow** — explore an entity, enter compare mode, adjust sliders, verify color-coded overlay. Exit compare mode, verify single-slider mode is restored.

- [ ] **Step 4: Commit**

```bash
git add explore/static/js/app.js
git commit -m "feat(explore): wire compare mode callbacks in ExploreApp (#126)"
```

### Task 7: Disable Load-More in Comparison Mode

**Files:**
- Modify: `explore/static/js/graph.js:481-503` (`_onNodeClicked`)

- [ ] **Step 1: Guard load-more clicks in compare mode**

In `_onNodeClicked`, replace the load-more check (lines 485-488):

```javascript
if (d.isLoadMore) {
    this._loadMoreCategory(d);
    return;
}
```

with:

```javascript
if (d.isLoadMore) {
    if (!this.compareMode) {
        this._loadMoreCategory(d);
    }
    return;
}
```

- [ ] **Step 2: Commit**

```bash
git add explore/static/js/graph.js
git commit -m "feat(explore): disable load-more during comparison mode (#126)"
```

### Task 8: Final Integration Verification

- [ ] **Step 1: Test the complete flow manually**

1. Open Explore, search for an entity (e.g., an artist)
2. Wait for graph to load with categories expanded
3. Use single-slider timeline — verify it still works as before
4. Click Compare button — verify dual sliders appear, legend appears
5. Drag Year A to 1980 and Year B to 2000 — verify nodes are color-coded:
   - Normal nodes (both years)
   - Dashed/faded nodes (Year A only)
   - Green-glowing nodes (Year B only)
6. Drag both sliders to the same year — verify "Select different years to compare" hint
7. Click close (X) — verify single slider restores, graph re-renders with saved year
8. Verify play/pause/speed controls work after exiting compare mode

- [ ] **Step 2: Commit spec and plan docs**

```bash
git add docs/superpowers/specs/2026-03-15-snapshot-comparison-design.md
git add docs/superpowers/plans/2026-03-15-snapshot-comparison.md
git commit -m "docs: add snapshot comparison spec and implementation plan (#126)"
```
