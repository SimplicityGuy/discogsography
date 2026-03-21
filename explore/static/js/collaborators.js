/**
 * Collaborators panel — shows artists who have collaborated on releases.
 * Renders a list with D3 sparklines showing collaboration activity over time.
 */
class CollaboratorsPanel {
    constructor() {
        // No DOM dependencies at construction time
    }

    /**
     * Load collaborators for an artist and render into the container.
     * @param {string} artistId - Neo4j artist ID
     */
    async load(artistId) {
        const data = await window.apiClient.getCollaborators(artistId);
        if (!data) return;
        const container = document.getElementById('collaboratorsContainer');
        if (!container) return;
        this._renderList(container, data);
    }

    /**
     * Render the collaborator list into a container element.
     * @param {HTMLElement} container - Target container
     * @param {Object} data - Collaborators API response
     */
    _renderList(container, data) {
        container.textContent = '';
        if (!data.collaborators?.length) {
            const msg = document.createElement('p');
            msg.className = 'text-text-mid text-sm';
            msg.textContent = 'No collaborators found';
            container.appendChild(msg);
            return;
        }

        const list = document.createElement('div');
        list.className = 'collaborator-list';

        data.collaborators.forEach((collab) => {
            const item = document.createElement('div');
            item.className = 'collaborator-item';

            // Name link (clickable to explore)
            const nameEl = document.createElement('a');
            nameEl.className = 'collaborator-name';
            nameEl.href = '#';
            nameEl.textContent = collab.artist_name;
            nameEl.addEventListener('click', (e) => {
                e.preventDefault();
                if (window.exploreApp) {
                    window.exploreApp._onNodeExpand(collab.artist_name, 'artist');
                }
            });

            // Release count + year range
            const meta = document.createElement('span');
            meta.className = 'collaborator-meta';
            const plural = collab.release_count !== 1 ? 's' : '';
            meta.textContent = `${collab.release_count} release${plural} (${collab.first_year}\u2013${collab.last_year})`;

            // Sparkline
            const sparkContainer = document.createElement('div');
            sparkContainer.className = 'collaborator-sparkline';
            if (collab.yearly_counts?.length) {
                this._drawSparkline(sparkContainer, collab.yearly_counts);
            }

            item.append(nameEl, meta, sparkContainer);
            list.appendChild(item);
        });

        container.appendChild(list);

        if (data.total > data.collaborators.length) {
            const more = document.createElement('p');
            more.className = 'text-text-mid text-sm mt-2';
            more.textContent = `Showing ${data.collaborators.length} of ${data.total} collaborators`;
            container.appendChild(more);
        }
    }

    /**
     * Draw a tiny sparkline SVG inside the given container using D3.
     * @param {HTMLElement} container - Target element for the SVG
     * @param {Array<{year: number, count: number}>} yearlyCounts - Data points
     */
    _drawSparkline(container, yearlyCounts) {
        const width = 120;
        const height = 24;
        const margin = { top: 2, right: 2, bottom: 2, left: 2 };

        const svg = d3
            .select(container)
            .append('svg')
            .attr('width', width)
            .attr('height', height)
            .attr('class', 'sparkline-svg');

        const [minYear, maxYear] = d3.extent(yearlyCounts, (d) => d.year);
        const x = d3
            .scaleLinear()
            .domain([minYear, maxYear === minYear ? minYear + 1 : maxYear])
            .range([margin.left, width - margin.right]);

        const maxCount = d3.max(yearlyCounts, (d) => d.count) || 1;
        const y = d3
            .scaleLinear()
            .domain([0, maxCount])
            .range([height - margin.bottom, margin.top]);

        const line = d3
            .line()
            .x((d) => x(d.year))
            .y((d) => y(d.count))
            .curve(d3.curveMonotoneX);

        svg.append('path')
            .datum(yearlyCounts)
            .attr('fill', 'none')
            .attr('stroke', 'var(--purple-accent)')
            .attr('stroke-width', 1.5)
            .attr('d', line);

        // Dots
        svg.selectAll('circle')
            .data(yearlyCounts)
            .enter()
            .append('circle')
            .attr('cx', (d) => x(d.year))
            .attr('cy', (d) => y(d.count))
            .attr('r', 2)
            .attr('fill', 'var(--purple-accent)');
    }
}

window.collaboratorsPanel = new CollaboratorsPanel();
