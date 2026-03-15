/**
 * Search pane — full-text search with type/genre/year filters and faceted results.
 */
(function initSearchPane() {
    'use strict';

    // DOM refs
    const input       = document.getElementById('searchPaneInput');
    const chipWrap    = document.getElementById('searchTypeChips');
    const yearMinEl   = document.getElementById('searchYearMin');
    const yearMaxEl   = document.getElementById('searchYearMax');
    const genreWrap   = document.getElementById('searchGenreFilter');
    const facetsEl    = document.getElementById('searchFacets');
    const loadingEl   = document.getElementById('searchLoading');
    const placeholder = document.getElementById('searchPlaceholder');
    const resultsEl   = document.getElementById('searchResults');
    const paginationEl = document.getElementById('searchPagination');

    if (!input) return;

    const PAGE_SIZE = 20;
    let debounceTimer;
    let currentOffset = 0;
    let lastQuery = '';
    let lastResult = null;
    let selectedGenres = [];

    // ------------------------------------------------------------------
    // Parse ts_headline highlight into DOM nodes (no innerHTML)
    // ts_headline output contains only <b>matched</b> segments.
    // ------------------------------------------------------------------

    function buildHighlightNodes(highlight) {
        const fragment = document.createDocumentFragment();
        if (!highlight || typeof highlight !== 'string') return fragment;
        // Split on <b>...</b> boundaries
        const parts = highlight.split(/(<b>.*?<\/b>)/gi);
        parts.forEach(part => {
            const match = part.match(/^<b>(.*?)<\/b>$/i);
            if (match) {
                const b = document.createElement('b');
                b.textContent = match[1];
                fragment.appendChild(b);
            } else if (part) {
                fragment.appendChild(document.createTextNode(part));
            }
        });
        return fragment;
    }

    // ------------------------------------------------------------------
    // Type chip toggles
    // ------------------------------------------------------------------

    chipWrap.addEventListener('click', (e) => {
        const chip = e.target.closest('[data-search-type]');
        if (!chip) return;
        chip.classList.toggle('active');
        triggerSearch();
    });

    function getActiveTypes() {
        return Array.from(chipWrap.querySelectorAll('.active[data-search-type]'))
            .map(el => el.dataset.searchType);
    }

    // ------------------------------------------------------------------
    // Year range inputs
    // ------------------------------------------------------------------

    let yearTimer;
    [yearMinEl, yearMaxEl].forEach(el => {
        el.addEventListener('input', () => {
            clearTimeout(yearTimer);
            yearTimer = setTimeout(() => triggerSearch(), 500);
        });
    });

    // ------------------------------------------------------------------
    // Debounced search input
    // ------------------------------------------------------------------

    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const q = input.value.trim();
        if (q.length < 3) {
            showPlaceholder();
            return;
        }
        debounceTimer = setTimeout(() => {
            currentOffset = 0;
            triggerSearch();
        }, 300);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            clearTimeout(debounceTimer);
            currentOffset = 0;
            triggerSearch();
        }
    });

    // ------------------------------------------------------------------
    // Core search
    // ------------------------------------------------------------------

    async function triggerSearch() {
        const q = input.value.trim();
        if (q.length < 3) {
            showPlaceholder();
            return;
        }

        lastQuery = q;
        setVisible(placeholder, false);
        setVisible(loadingEl, true);
        setVisible(resultsEl, false);
        paginationEl.textContent = '';
        facetsEl.textContent = '';

        const types = getActiveTypes();
        const yearMin = yearMinEl.value ? parseInt(yearMinEl.value, 10) : null;
        const yearMax = yearMaxEl.value ? parseInt(yearMaxEl.value, 10) : null;

        const data = await window.apiClient.search(q, types, selectedGenres, yearMin, yearMax, PAGE_SIZE, currentOffset);

        setVisible(loadingEl, false);

        if (!data || !data.results) {
            resultsEl.textContent = '';
            const msg = document.createElement('p');
            msg.className = 'text-text-secondary text-center py-8';
            msg.textContent = 'An error occurred. Please try again.';
            resultsEl.appendChild(msg);
            setVisible(resultsEl, true);
            return;
        }

        lastResult = data;
        renderFacets(data.facets);
        renderResults(data.results, data.total);
        renderPagination(data.total, data.pagination);
        setVisible(resultsEl, true);
    }

    // ------------------------------------------------------------------
    // Facets
    // ------------------------------------------------------------------

    function renderFacets(facets) {
        facetsEl.textContent = '';
        if (!facets) return;

        // Type facets
        if (facets.type) {
            const row = document.createElement('div');
            row.className = 'search-facet-row';
            Object.entries(facets.type).forEach(([type, count]) => {
                if (count === 0) return;
                const tag = document.createElement('span');
                tag.className = 'search-facet-tag';
                tag.textContent = `${type} (${count.toLocaleString()})`;
                row.appendChild(tag);
            });
            if (row.children.length) facetsEl.appendChild(row);
        }

        // Genre facets as clickable chips
        if (facets.genre && Object.keys(facets.genre).length) {
            genreWrap.textContent = '';
            const label = document.createElement('label');
            label.className = 'search-filter-label';
            label.textContent = 'Genres';
            genreWrap.appendChild(label);

            const chips = document.createElement('div');
            chips.className = 'search-genre-chips';
            const entries = Object.entries(facets.genre).slice(0, 12);
            entries.forEach(([genre, count]) => {
                const chip = document.createElement('button');
                chip.className = 'search-chip search-chip-sm';
                if (selectedGenres.includes(genre)) chip.classList.add('active');
                chip.textContent = `${genre} (${count})`;
                chip.addEventListener('click', () => {
                    const idx = selectedGenres.indexOf(genre);
                    if (idx >= 0) {
                        selectedGenres.splice(idx, 1);
                        chip.classList.remove('active');
                    } else {
                        selectedGenres.push(genre);
                        chip.classList.add('active');
                    }
                    currentOffset = 0;
                    triggerSearch();
                });
                chips.appendChild(chip);
            });
            genreWrap.appendChild(chips);
        }

        // Decade facets
        if (facets.decade && Object.keys(facets.decade).length) {
            const row = document.createElement('div');
            row.className = 'search-facet-row';
            Object.entries(facets.decade)
                .sort(([a], [b]) => a.localeCompare(b))
                .forEach(([decade, count]) => {
                    if (count === 0) return;
                    const tag = document.createElement('span');
                    tag.className = 'search-facet-tag search-facet-decade';
                    tag.textContent = `${decade} (${count.toLocaleString()})`;
                    row.appendChild(tag);
                });
            if (row.children.length) facetsEl.appendChild(row);
        }
    }

    // ------------------------------------------------------------------
    // Results
    // ------------------------------------------------------------------

    function renderResults(results, total) {
        resultsEl.textContent = '';

        if (results.length === 0) {
            const msg = document.createElement('div');
            msg.className = 'search-no-results';
            const icon = document.createElement('i');
            icon.className = 'fas fa-search fa-2x mb-2';
            msg.appendChild(icon);
            const txt = document.createElement('p');
            txt.textContent = `No results found for "${lastQuery}"`;
            msg.appendChild(txt);
            resultsEl.appendChild(msg);
            return;
        }

        const header = document.createElement('div');
        header.className = 'search-results-header';
        header.textContent = `${total.toLocaleString()} result${total === 1 ? '' : 's'}`;
        resultsEl.appendChild(header);

        const list = document.createElement('div');
        list.className = 'search-results-list';

        results.forEach(r => {
            const card = document.createElement('div');
            card.className = 'search-result-card';
            card.addEventListener('click', () => navigateToResult(r));

            // Type badge
            const badge = document.createElement('span');
            badge.className = `search-result-badge search-badge-${r.type}`;
            badge.textContent = r.type;

            // Name — use sanitized highlight if available, plain text otherwise
            const name = document.createElement('span');
            name.className = 'search-result-name';
            if (r.highlight) {
                name.appendChild(buildHighlightNodes(r.highlight));
            } else {
                name.textContent = r.name;
            }

            // Metadata line
            const meta = document.createElement('span');
            meta.className = 'search-result-meta';
            const parts = [];
            if (r.metadata?.year) parts.push(String(r.metadata.year));
            if (r.metadata?.genres?.length) parts.push(r.metadata.genres.slice(0, 3).join(', '));
            meta.textContent = parts.join(' \u00B7 ');

            // Relevance indicator
            const rel = document.createElement('span');
            rel.className = 'search-result-relevance';
            const pct = Math.min(100, Math.round((r.relevance || 0) * 100));
            rel.title = `Relevance: ${pct}%`;
            const bar = document.createElement('span');
            bar.className = 'search-relevance-bar';
            bar.style.width = `${pct}%`;
            rel.appendChild(bar);

            card.append(badge, name, meta, rel);
            list.appendChild(card);
        });

        resultsEl.appendChild(list);
    }

    // ------------------------------------------------------------------
    // Pagination
    // ------------------------------------------------------------------

    function renderPagination(total, pagination) {
        paginationEl.textContent = '';
        if (!pagination || (!pagination.has_more && currentOffset === 0)) return;

        const totalPages = Math.ceil(total / PAGE_SIZE);
        const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;

        const info = document.createElement('span');
        info.className = 'page-info';
        const start = currentOffset + 1;
        const end = Math.min(currentOffset + PAGE_SIZE, total);
        info.textContent = `${start}-${end} of ${total.toLocaleString()}`;

        const buttons = document.createElement('div');
        buttons.className = 'page-buttons';

        // Previous
        const prevBtn = document.createElement('button');
        prevBtn.className = 'page-btn';
        const prevIcon = document.createElement('i');
        prevIcon.className = 'fas fa-chevron-left';
        prevBtn.appendChild(prevIcon);
        prevBtn.disabled = currentPage === 1;
        prevBtn.addEventListener('click', () => {
            currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
            triggerSearch();
        });
        buttons.appendChild(prevBtn);

        // Page numbers
        const pages = getPageNumbers(currentPage, totalPages);
        pages.forEach(p => {
            if (p === '...') {
                const ell = document.createElement('span');
                ell.className = 'page-ellipsis';
                ell.textContent = '...';
                buttons.appendChild(ell);
            } else {
                const btn = document.createElement('button');
                btn.className = 'page-btn';
                if (p === currentPage) btn.classList.add('active');
                btn.textContent = String(p);
                btn.addEventListener('click', () => {
                    currentOffset = (p - 1) * PAGE_SIZE;
                    triggerSearch();
                });
                buttons.appendChild(btn);
            }
        });

        // Next
        const nextBtn = document.createElement('button');
        nextBtn.className = 'page-btn';
        const nextIcon = document.createElement('i');
        nextIcon.className = 'fas fa-chevron-right';
        nextBtn.appendChild(nextIcon);
        nextBtn.disabled = currentPage >= totalPages;
        nextBtn.addEventListener('click', () => {
            currentOffset += PAGE_SIZE;
            triggerSearch();
        });
        buttons.appendChild(nextBtn);

        paginationEl.append(info, buttons);
    }

    function getPageNumbers(current, total) {
        if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
        const pages = [];
        if (current <= 4) {
            for (let i = 1; i <= 5; i++) pages.push(i);
            pages.push('...', total);
        } else if (current >= total - 3) {
            pages.push(1, '...');
            for (let i = total - 4; i <= total; i++) pages.push(i);
        } else {
            pages.push(1, '...', current - 1, current, current + 1, '...', total);
        }
        return pages;
    }

    // ------------------------------------------------------------------
    // Navigate to Explore pane on result click
    // ------------------------------------------------------------------

    function navigateToResult(result) {
        const explorableTypes = ['artist', 'label'];
        const type = result.type;
        const name = result.name;

        if (explorableTypes.includes(type) && window.exploreApp) {
            window.exploreApp._setSearchType(type);
            window.exploreApp.currentQuery = name;
            document.getElementById('searchInput').value = name;
            window.exploreApp._switchPane('explore');
            window.exploreApp._loadExplore(name, type);
        } else if (window.exploreApp) {
            // For release/master — switch to explore pane
            window.exploreApp._switchPane('explore');
        }
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    function setVisible(el, visible) {
        if (!el) return;
        if (el === loadingEl) {
            el.classList.toggle('active', visible);
        } else {
            el.classList.toggle('hidden', !visible);
        }
    }

    function showPlaceholder() {
        setVisible(loadingEl, false);
        setVisible(resultsEl, false);
        paginationEl.textContent = '';
        facetsEl.textContent = '';
        genreWrap.textContent = '';
        setVisible(placeholder, true);
    }

    // ------------------------------------------------------------------
    // Public API for app.js pane switching
    // ------------------------------------------------------------------

    window.searchPane = {
        focus() {
            input.focus();
        },
    };
})();
