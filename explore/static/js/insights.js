/**
 * Insights panel — displays precomputed analytics from the Insights Service.
 * Includes auto-refresh polling (#132).
 */
class InsightsPanel {
    constructor() {
        this._loaded = false;
        this._pollInterval = null;
        this._lastComputedAt = null;
        this._selectedGenre = 'Rock';

        this._container = document.getElementById('insightsPane');
        this._loading = document.getElementById('insightsLoading');
        this._placeholder = document.getElementById('insightsPlaceholder');
        this._content = document.getElementById('insightsContent');
    }

    async load() {
        if (this._loading) this._loading.classList.add('active');
        if (this._placeholder) this._placeholder.classList.add('hidden');

        try {
            const [artists, thisMonth, completeness, status] = await Promise.all([
                window.apiClient.getInsightsTopArtists(10),
                window.apiClient.getInsightsThisMonth(),
                window.apiClient.getInsightsDataCompleteness(),
                window.apiClient.getInsightsStatus(),
            ]);

            const hasData = artists || thisMonth || completeness || status;
            if (!hasData) {
                this._showEmpty();
                return;
            }

            if (this._content) this._content.classList.remove('hidden');

            this._renderTopArtists(artists);
            this._renderThisMonth(thisMonth);
            this._renderDataCompleteness(completeness);
            this._renderStatus(status);
            await this._loadGenreTrends(this._selectedGenre);

            // Store timestamps for polling
            if (status?.statuses) {
                this._lastComputedAt = new Map(
                    status.statuses.map(s => [s.insight_type, s.last_computed])
                );
            }

            this._loaded = true;
        } catch {
            this._showEmpty();
        } finally {
            if (this._loading) this._loading.classList.remove('active');
        }
    }

    _showEmpty() {
        if (this._content) this._content.classList.add('hidden');
        if (this._placeholder) this._placeholder.classList.remove('hidden');
    }

    // ----------------------------------------------------------------
    // Top Artists
    // ----------------------------------------------------------------

    _renderTopArtists(data) {
        const el = document.getElementById('insightsTopArtists');
        if (!el) return;

        if (!data?.items?.length) {
            el.textContent = '';
            const msg = document.createElement('p');
            msg.className = 'text-text-mid text-sm';
            msg.textContent = 'No data available yet';
            el.appendChild(msg);
            return;
        }

        const rows = data.items.map(a => {
            const tr = document.createElement('tr');
            const tdRank = document.createElement('td');
            tdRank.className = 'insights-table-cell text-text-mid';
            tdRank.textContent = String(a.rank);
            const tdName = document.createElement('td');
            tdName.className = 'insights-table-cell';
            tdName.textContent = a.artist_name;
            const tdCount = document.createElement('td');
            tdCount.className = 'insights-table-cell text-right text-text-mid';
            tdCount.textContent = a.edge_count.toLocaleString();
            tr.append(tdRank, tdName, tdCount);
            return tr;
        });

        el.textContent = '';
        const table = document.createElement('table');
        table.className = 'insights-table';

        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        ['#', 'Artist', 'Connections'].forEach((text, i) => {
            const th = document.createElement('th');
            th.className = 'insights-table-header' + (i === 2 ? ' text-right' : '');
            th.textContent = text;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);

        const tbody = document.createElement('tbody');
        rows.forEach(r => tbody.appendChild(r));
        table.append(thead, tbody);
        el.appendChild(table);
    }

    // ----------------------------------------------------------------
    // Genre Trends
    // ----------------------------------------------------------------

    async _loadGenreTrends(genre) {
        this._selectedGenre = genre;

        // Update active chip
        document.querySelectorAll('.insights-genre-chip').forEach(chip => {
            chip.classList.toggle('active', chip.dataset.genre === genre);
        });

        const data = await window.apiClient.getInsightsGenreTrends(genre);
        this._renderGenreTrends(data);
    }

    _renderGenreTrends(data) {
        const el = document.getElementById('insightsGenreChart');
        if (!el) return;

        if (!data?.trends?.length) {
            el.textContent = '';
            const msg = document.createElement('p');
            msg.className = 'text-text-mid text-sm';
            msg.textContent = 'No trend data for this genre';
            el.appendChild(msg);
            return;
        }

        const decades = data.trends.map(t => t.decade);
        const counts = data.trends.map(t => t.release_count);

        const trace = {
            x: decades,
            y: counts,
            type: 'scatter',
            mode: 'lines+markers',
            fill: 'tozeroy',
            fillcolor: 'rgba(107, 70, 193, 0.15)',
            line: { color: '#6b46c1', width: 2 },
            marker: { color: '#6b46c1', size: 6 },
            name: data.genre,
        };

        const layout = {
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            margin: { t: 10, r: 20, b: 40, l: 50 },
            xaxis: {
                title: 'Decade',
                color: '#b0b3b8',
                gridcolor: '#2d3051',
                tickformat: 'd',
            },
            yaxis: {
                title: 'Releases',
                color: '#b0b3b8',
                gridcolor: '#2d3051',
            },
            font: { color: '#e4e6eb', family: 'system-ui, sans-serif' },
            showlegend: false,
            height: 250,
        };

        Plotly.newPlot(el, [trace], layout, { responsive: true, displayModeBar: false });
    }

    // ----------------------------------------------------------------
    // This Month in Music History
    // ----------------------------------------------------------------

    _renderThisMonth(data) {
        const el = document.getElementById('insightsThisMonth');
        if (!el) return;

        if (!data?.items?.length) {
            el.textContent = '';
            const msg = document.createElement('p');
            msg.className = 'text-text-mid text-sm';
            msg.textContent = 'No anniversaries this month';
            el.appendChild(msg);
            return;
        }

        // Group by anniversary
        const groups = new Map();
        for (const item of data.items) {
            const key = item.anniversary;
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(item);
        }

        el.textContent = '';
        for (const [years, items] of groups) {
            const section = document.createElement('div');
            section.className = 'insights-anniversary-group';

            const heading = document.createElement('h4');
            heading.className = 'insights-anniversary-heading';
            heading.textContent = `${years} Years Ago`;
            section.appendChild(heading);

            const list = document.createElement('div');
            list.className = 'insights-anniversary-list';
            for (const item of items) {
                const card = document.createElement('div');
                card.className = 'insights-anniversary-card';

                const title = document.createElement('span');
                title.className = 'insights-anniversary-title';
                title.textContent = item.title;

                const artist = document.createElement('span');
                artist.className = 'insights-anniversary-artist';
                artist.textContent = item.artist_name || 'Unknown Artist';

                const year = document.createElement('span');
                year.className = 'insights-anniversary-year';
                year.textContent = String(item.release_year);

                card.append(title, artist, year);
                list.appendChild(card);
            }
            section.appendChild(list);
            el.appendChild(section);
        }
    }

    // ----------------------------------------------------------------
    // Data Completeness
    // ----------------------------------------------------------------

    _renderDataCompleteness(data) {
        const el = document.getElementById('insightsCompleteness');
        if (!el) return;

        if (!data?.items?.length) {
            el.textContent = '';
            const msg = document.createElement('p');
            msg.className = 'text-text-mid text-sm';
            msg.textContent = 'No completeness data available';
            el.appendChild(msg);
            return;
        }

        el.textContent = '';
        for (const item of data.items) {
            const row = document.createElement('div');
            row.className = 'insights-completeness-row';

            const label = document.createElement('span');
            label.className = 'insights-completeness-label';
            label.textContent = item.entity_type.charAt(0).toUpperCase() + item.entity_type.slice(1);

            const barContainer = document.createElement('div');
            barContainer.className = 'insights-completeness-bar-container';

            const bar = document.createElement('div');
            bar.className = 'insights-completeness-bar';
            bar.style.width = `${Math.min(100, item.completeness_pct)}%`;

            const pct = document.createElement('span');
            pct.className = 'insights-completeness-pct';
            pct.textContent = `${item.completeness_pct.toFixed(1)}%`;

            const count = document.createElement('span');
            count.className = 'insights-completeness-count';
            count.textContent = item.total_count.toLocaleString();

            barContainer.appendChild(bar);
            row.append(label, barContainer, pct, count);
            el.appendChild(row);
        }
    }

    // ----------------------------------------------------------------
    // Status Footer
    // ----------------------------------------------------------------

    _renderStatus(data) {
        const el = document.getElementById('insightsStatus');
        if (!el) return;

        if (!data?.statuses?.length) {
            el.textContent = '';
            return;
        }

        const latest = data.statuses
            .filter(s => s.last_computed)
            .map(s => new Date(s.last_computed))
            .sort((a, b) => b - a)[0];

        const allHealthy = data.statuses.every(s => s.status === 'completed' || s.status === 'never_run');

        el.textContent = '';
        const wrapper = document.createElement('div');
        wrapper.className = 'insights-status-bar';

        if (latest) {
            const timeAgo = this._timeAgo(latest);
            const timeSpan = document.createElement('span');
            timeSpan.className = 'text-text-mid text-xs';
            timeSpan.textContent = `Last computed ${timeAgo}`;
            wrapper.appendChild(timeSpan);
        }

        const statusDot = document.createElement('span');
        statusDot.className = `insights-status-dot ${allHealthy ? 'healthy' : 'warning'}`;
        statusDot.textContent = allHealthy ? 'All healthy' : 'Issues detected';
        wrapper.appendChild(statusDot);

        el.appendChild(wrapper);
    }

    _timeAgo(date) {
        const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
        if (seconds < 60) return 'just now';
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        return `${days}d ago`;
    }

    // ----------------------------------------------------------------
    // Auto-refresh polling (#132)
    // ----------------------------------------------------------------

    startPolling() {
        if (this._pollInterval) return;
        this._pollInterval = setInterval(() => this._checkForUpdates(), 60000);
    }

    stopPolling() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    async _checkForUpdates() {
        try {
            const status = await window.apiClient.getInsightsStatus();
            if (!status?.statuses) return;

            const newTimestamps = new Map(
                status.statuses.map(s => [s.insight_type, s.last_computed])
            );

            if (this._lastComputedAt && this._hasChanged(newTimestamps)) {
                await this.load();
            }

            this._lastComputedAt = newTimestamps;
        } catch {
            // Skip this poll, retry next interval
        }
    }

    _hasChanged(newTimestamps) {
        if (!this._lastComputedAt) return false;
        if (newTimestamps.size !== this._lastComputedAt.size) return true;
        for (const [type, ts] of newTimestamps) {
            if (ts !== this._lastComputedAt.get(type)) return true;
        }
        return false;
    }
}

// Global instance
window.insightsPanel = new InsightsPanel();
