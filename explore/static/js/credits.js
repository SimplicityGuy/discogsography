/**
 * Credits & Provenance panel — the people behind the music.
 *
 * Provides person search, profile cards, timeline charts, release lists,
 * connections graphs, and role leaderboards.
 */
class CreditsPanel {
    constructor() {
        this._currentPerson = null;
        this._allCredits = [];
        this._activeFilter = null;
        this._debounceTimer = null;
        this._leaderboardLoaded = false;
        this._init();
    }

    _init() {
        const input = document.getElementById('creditsSearchInput');
        if (input) {
            input.addEventListener('input', () => this._onSearchInput(input.value));
            input.addEventListener('keydown', (e) => this._onSearchKeydown(e));
        }

        const dropdown = document.getElementById('creditsAutocompleteDropdown');
        if (dropdown) {
            document.addEventListener('click', (e) => {
                if (!dropdown.contains(e.target) && e.target !== input) {
                    dropdown.classList.add('hidden');
                }
            });
        }

        const categorySelect = document.getElementById('creditsLeaderboardCategory');
        if (categorySelect) {
            categorySelect.addEventListener('change', () => {
                this._loadLeaderboard(categorySelect.value);
            });
        }
    }

    // ── Search & Autocomplete ─────────────────────────────────────────── //

    _onSearchInput(value) {
        clearTimeout(this._debounceTimer);
        const query = value.trim();
        if (query.length < 2) {
            this._hideDropdown();
            return;
        }
        this._debounceTimer = setTimeout(() => this._searchPerson(query), 300);
    }

    _onSearchKeydown(e) {
        const dropdown = document.getElementById('creditsAutocompleteDropdown');
        if (!dropdown || dropdown.classList.contains('hidden')) return;

        const items = dropdown.querySelectorAll('.autocomplete-item');
        const active = dropdown.querySelector('.autocomplete-item.active');
        let idx = Array.from(items).indexOf(active);

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (active) active.classList.remove('active');
            idx = Math.min(idx + 1, items.length - 1);
            items[idx]?.classList.add('active');
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (active) active.classList.remove('active');
            idx = Math.max(idx - 1, 0);
            items[idx]?.classList.add('active');
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const sel = dropdown.querySelector('.autocomplete-item.active');
            if (sel) this._selectPerson(sel.dataset.name);
        } else if (e.key === 'Escape') {
            this._hideDropdown();
        }
    }

    async _searchPerson(query) {
        try {
            const resp = await fetch(`/api/credits/autocomplete?q=${encodeURIComponent(query)}&limit=10`);
            if (!resp.ok) return;
            const data = await resp.json();
            this._showDropdown(data.results || []);
        } catch {
            // Silently fail
        }
    }

    _showDropdown(results) {
        const dropdown = document.getElementById('creditsAutocompleteDropdown');
        if (!dropdown) return;

        if (!results.length) {
            dropdown.classList.add('hidden');
            return;
        }

        dropdown.textContent = '';
        results.forEach(r => {
            const item = document.createElement('div');
            item.className = 'autocomplete-item';
            item.dataset.name = r.name;
            item.textContent = r.name;
            item.addEventListener('click', () => this._selectPerson(r.name));
            dropdown.appendChild(item);
        });

        dropdown.classList.remove('hidden');
    }

    _hideDropdown() {
        const dropdown = document.getElementById('creditsAutocompleteDropdown');
        if (dropdown) dropdown.classList.add('hidden');
    }

    async _selectPerson(name) {
        this._hideDropdown();
        const input = document.getElementById('creditsSearchInput');
        if (input) input.value = name;
        this._currentPerson = name;
        await this._loadPersonData(name);
    }

    // ── Data Loading ──────────────────────────────────────────────────── //

    async _loadPersonData(name) {
        this._showLoading(true);
        this._hideEmptyState();

        try {
            const [profileResp, creditsResp, timelineResp, connectionsResp] = await Promise.allSettled([
                fetch(`/api/credits/person/${encodeURIComponent(name)}/profile`),
                fetch(`/api/credits/person/${encodeURIComponent(name)}`),
                fetch(`/api/credits/person/${encodeURIComponent(name)}/timeline`),
                fetch(`/api/credits/connections/${encodeURIComponent(name)}?depth=1&limit=30`),
            ]);

            if (profileResp.status === 'fulfilled' && profileResp.value.ok) {
                const profile = await profileResp.value.json();
                this._renderProfile(profile);
            }

            if (creditsResp.status === 'fulfilled' && creditsResp.value.ok) {
                const credits = await creditsResp.value.json();
                this._allCredits = credits.credits || [];
                this._renderReleaseList(this._allCredits);
            }

            if (timelineResp.status === 'fulfilled' && timelineResp.value.ok) {
                const timeline = await timelineResp.value.json();
                this._renderTimeline(timeline.timeline || []);
            }

            if (connectionsResp.status === 'fulfilled' && connectionsResp.value.ok) {
                const connections = await connectionsResp.value.json();
                this._renderConnections(connections.connections || [], name);
            }

            // Load leaderboard on first visit
            if (!this._leaderboardLoaded) {
                this._loadLeaderboard('mastering');
                this._leaderboardLoaded = true;
            }
        } catch {
            // Silently fail
        } finally {
            this._showLoading(false);
        }
    }

    async _loadLeaderboard(category) {
        const list = document.getElementById('creditsLeaderboardList');
        const section = document.getElementById('creditsLeaderboardSection');
        if (!list || !section) return;

        section.classList.remove('hidden');

        try {
            const resp = await fetch(`/api/credits/role/${encodeURIComponent(category)}/top?limit=20`);
            if (!resp.ok) return;
            const data = await resp.json();
            this._renderLeaderboard(data.entries || []);
        } catch {
            list.textContent = '';
            const msg = document.createElement('p');
            msg.className = 'text-text-mid';
            msg.textContent = 'Could not load leaderboard.';
            list.appendChild(msg);
        }
    }

    // ── Rendering ─────────────────────────────────────────────────────── //

    _renderProfile(profile) {
        const card = document.getElementById('creditsProfileCard');
        if (!card) return;

        document.getElementById('creditsPersonName').textContent = profile.name;
        document.getElementById('creditsTotalCount').textContent = `${profile.total_credits} credits`;

        const yearsEl = document.getElementById('creditsActiveYears');
        if (profile.first_year && profile.last_year) {
            yearsEl.textContent = `Active: ${profile.first_year}\u2013${profile.last_year}`;
        } else {
            yearsEl.textContent = '';
        }

        // Artist link
        const artistLink = document.getElementById('creditsArtistLink');
        if (profile.artist_id) {
            artistLink.classList.remove('hidden');
            artistLink.onclick = (e) => {
                e.preventDefault();
                if (window.exploreApp) {
                    window.exploreApp._switchPane('explore');
                    window.exploreApp._loadExplore(profile.artist_name || profile.name, 'artist');
                }
            };
        } else {
            artistLink.classList.add('hidden');
        }

        // Role breakdown pills
        const pillsEl = document.getElementById('creditsRoleBreakdown');
        pillsEl.textContent = '';
        (profile.role_breakdown || []).forEach(r => {
            const pill = document.createElement('span');
            pill.className = `credits-role-pill credits-role-${r.category}`;
            pill.textContent = `${r.category} (${r.count})`;
            pillsEl.appendChild(pill);
        });

        card.classList.remove('hidden');
    }

    _renderTimeline(timeline) {
        const section = document.getElementById('creditsTimelineSection');
        const chartEl = document.getElementById('creditsTimelineChart');
        if (!section || !chartEl) return;

        if (!timeline.length) {
            section.classList.add('hidden');
            return;
        }

        section.classList.remove('hidden');

        // Group by category
        const categories = {};
        timeline.forEach(t => {
            if (!categories[t.category]) categories[t.category] = { x: [], y: [] };
            categories[t.category].x.push(t.year);
            categories[t.category].y.push(t.count);
        });

        const categoryColors = {
            production: '#7c3aed',
            engineering: '#2563eb',
            mastering: '#dc2626',
            session: '#16a34a',
            design: '#ea580c',
            management: '#0891b2',
            other: '#6b7280',
        };

        const traces = Object.entries(categories).map(([cat, data]) => ({
            x: data.x,
            y: data.y,
            name: cat,
            type: 'bar',
            marker: { color: categoryColors[cat] || '#6b7280' },
        }));

        const layout = {
            barmode: 'stack',
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            font: { color: '#9ca3af', size: 11 },
            margin: { t: 10, r: 10, b: 30, l: 30 },
            height: 200,
            showlegend: true,
            legend: { orientation: 'h', y: -0.2, font: { size: 10 } },
            xaxis: { gridcolor: '#374151' },
            yaxis: { gridcolor: '#374151' },
        };

        if (typeof Plotly !== 'undefined') {
            Plotly.newPlot(chartEl, traces, layout, { responsive: true, displayModeBar: false });
        }
    }

    _renderReleaseList(credits) {
        const section = document.getElementById('creditsReleaseSection');
        const listEl = document.getElementById('creditsReleaseList');
        const filterEl = document.getElementById('creditsRoleFilter');
        if (!section || !listEl) return;

        if (!credits.length) {
            section.classList.add('hidden');
            return;
        }

        section.classList.remove('hidden');

        // Build filter pills
        const categories = [...new Set(credits.map(c => c.category))].sort();
        if (filterEl) {
            filterEl.textContent = '';

            const allPill = document.createElement('span');
            allPill.className = 'credits-filter-pill active';
            allPill.dataset.filter = 'all';
            allPill.textContent = 'All';
            filterEl.appendChild(allPill);

            categories.forEach(c => {
                const pill = document.createElement('span');
                pill.className = `credits-filter-pill credits-role-${c}`;
                pill.dataset.filter = c;
                pill.textContent = c;
                filterEl.appendChild(pill);
            });

            filterEl.querySelectorAll('.credits-filter-pill').forEach(pill => {
                pill.addEventListener('click', () => {
                    filterEl.querySelectorAll('.credits-filter-pill').forEach(p => p.classList.remove('active'));
                    pill.classList.add('active');
                    const filter = pill.dataset.filter;
                    this._activeFilter = filter === 'all' ? null : filter;
                    const filtered = this._activeFilter
                        ? this._allCredits.filter(c => c.category === this._activeFilter)
                        : this._allCredits;
                    this._renderCreditRows(listEl, filtered);
                });
            });
        }

        this._renderCreditRows(listEl, credits);
    }

    _renderCreditRows(container, credits) {
        container.textContent = '';
        credits.slice(0, 100).forEach(c => {
            const row = document.createElement('div');
            row.className = 'credits-release-row';

            const yearSpan = document.createElement('span');
            yearSpan.className = 'credits-release-year';
            yearSpan.textContent = c.year || '\u2014';

            const infoDiv = document.createElement('div');
            infoDiv.className = 'credits-release-info';

            const titleSpan = document.createElement('span');
            titleSpan.className = 'credits-release-title';
            titleSpan.textContent = c.title;

            const artistSpan = document.createElement('span');
            artistSpan.className = 'credits-release-artist text-text-mid';
            artistSpan.textContent = (c.artists || []).join(', ');

            infoDiv.appendChild(titleSpan);
            infoDiv.appendChild(artistSpan);

            const roleSpan = document.createElement('span');
            roleSpan.className = `credits-role-pill credits-role-${c.category}`;
            roleSpan.title = c.role;
            roleSpan.textContent = c.role;

            row.appendChild(yearSpan);
            row.appendChild(infoDiv);
            row.appendChild(roleSpan);
            container.appendChild(row);
        });

        if (credits.length > 100) {
            const msg = document.createElement('p');
            msg.className = 'text-text-mid mt-2';
            msg.textContent = `Showing first 100 of ${credits.length} credits.`;
            container.appendChild(msg);
        }
    }

    _renderConnections(connections, centerName) {
        const section = document.getElementById('creditsConnectionsSection');
        const graphEl = document.getElementById('creditsConnectionsGraph');
        if (!section || !graphEl) return;

        if (!connections.length) {
            section.classList.add('hidden');
            return;
        }

        section.classList.remove('hidden');
        graphEl.textContent = '';

        const width = graphEl.clientWidth || 400;
        const height = 300;

        const nodes = [{ id: centerName, group: 'center' }];
        const links = [];
        const nodeSet = new Set([centerName]);

        connections.forEach(c => {
            if (!nodeSet.has(c.name)) {
                nodes.push({ id: c.name, group: 'connected', shared: c.shared_count });
                nodeSet.add(c.name);
            }
            links.push({ source: centerName, target: c.name, value: c.shared_count });
        });

        if (typeof d3 === 'undefined') return;

        const svg = d3.select(graphEl).append('svg')
            .attr('width', width).attr('height', height)
            .attr('viewBox', [0, 0, width, height]);

        const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.id).distance(80))
            .force('charge', d3.forceManyBody().strength(-200))
            .force('center', d3.forceCenter(width / 2, height / 2));

        const link = svg.append('g')
            .selectAll('line')
            .data(links)
            .join('line')
            .attr('stroke', '#4b5563')
            .attr('stroke-width', d => Math.max(1, Math.min(d.value / 2, 5)));

        const node = svg.append('g')
            .selectAll('circle')
            .data(nodes)
            .join('circle')
            .attr('r', d => d.group === 'center' ? 12 : Math.max(5, Math.min((d.shared || 1) * 2, 10)))
            .attr('fill', d => d.group === 'center' ? '#7c3aed' : '#3b82f6')
            .attr('stroke', '#1f2937')
            .attr('stroke-width', 1.5)
            .style('cursor', 'pointer')
            .on('click', (event, d) => {
                if (d.id !== centerName) {
                    this._selectPerson(d.id);
                }
            });

        const label = svg.append('g')
            .selectAll('text')
            .data(nodes)
            .join('text')
            .text(d => d.id.length > 20 ? d.id.substring(0, 18) + '\u2026' : d.id)
            .attr('font-size', 9)
            .attr('fill', '#d1d5db')
            .attr('text-anchor', 'middle')
            .attr('dy', d => d.group === 'center' ? -16 : -10);

        simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
            node.attr('cx', d => d.x).attr('cy', d => d.y);
            label.attr('x', d => d.x).attr('y', d => d.y);
        });
    }

    _renderLeaderboard(entries) {
        const list = document.getElementById('creditsLeaderboardList');
        if (!list) return;

        list.textContent = '';
        entries.forEach((e, i) => {
            const row = document.createElement('div');
            row.className = 'credits-leaderboard-row';

            const rankSpan = document.createElement('span');
            rankSpan.className = 'credits-leaderboard-rank';
            rankSpan.textContent = i + 1;

            const nameSpan = document.createElement('span');
            nameSpan.className = 'credits-leaderboard-name';
            nameSpan.textContent = e.name;
            nameSpan.style.cursor = 'pointer';
            nameSpan.addEventListener('click', () => this._selectPerson(e.name));

            const countSpan = document.createElement('span');
            countSpan.className = 'credits-leaderboard-count';
            countSpan.textContent = e.credit_count;

            row.appendChild(rankSpan);
            row.appendChild(nameSpan);
            row.appendChild(countSpan);
            list.appendChild(row);
        });
    }

    // ── Helpers ────────────────────────────────────────────────────────── //

    _showLoading(show) {
        const el = document.getElementById('creditsLoading');
        if (el) el.classList.toggle('active', show);
    }

    _hideEmptyState() {
        const el = document.getElementById('creditsEmptyState');
        if (el) el.classList.add('hidden');
    }

    /**
     * Called when the credits pane becomes active.
     * Loads leaderboard if not already loaded and no person selected.
     */
    load() {
        if (!this._currentPerson && !this._leaderboardLoaded) {
            this._loadLeaderboard('mastering');
            this._leaderboardLoaded = true;
        }
    }
}

window.creditsPanel = new CreditsPanel();
