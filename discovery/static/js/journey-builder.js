// Music Journey Builder Visualization

class JourneyBuilder {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.journey = null;
        this.selectedNodes = [];

        this.init();
    }

    init() {
        // Create journey visualization structure
        this.container.innerHTML = `
            <div class="journey-builder">
                <div class="journey-header">
                    <h5>Music Journey Path</h5>
                    <button class="btn btn-sm btn-outline-secondary" onclick="window.playground.visualizations.journey.exportJourney()">
                        <i class="fas fa-download"></i> Export
                    </button>
                </div>
                <div class="journey-path" id="journeyPath"></div>
                <div class="journey-stats" id="journeyStats"></div>
                <div class="journey-timeline" id="journeyTimeline"></div>
            </div>
        `;

        this.pathContainer = document.getElementById('journeyPath');
        this.statsContainer = document.getElementById('journeyStats');
        this.timelineContainer = document.getElementById('journeyTimeline');
    }

    render(journeyData) {
        if (!journeyData || !journeyData.journey) {
            this.showNoJourney();
            return;
        }

        this.journey = journeyData.journey;
        this.renderPath();
        this.renderStats();
        this.renderTimeline();
    }

    renderPath() {
        const nodes = this.journey.nodes;
        const relationships = this.journey.relationships;

        let pathHTML = '<div class="journey-nodes">';

        nodes.forEach((node, index) => {
            const isArtist = node.type === 'Artist';
            const icon = this.getNodeIcon(node.type);

            pathHTML += `
                <div class="journey-node ${node.type.toLowerCase()}" data-node-id="${node.id}">
                    <div class="node-icon">
                        <i class="fas ${icon}"></i>
                    </div>
                    <div class="node-info">
                        <div class="node-name">${node.name || 'Unknown'}</div>
                        <div class="node-type">${node.type}</div>
                        ${node.properties?.year ? `<div class="node-year">${node.properties.year}</div>` : ''}
                    </div>
                </div>
            `;

            if (index < relationships.length) {
                const rel = relationships[index];
                pathHTML += `
                    <div class="journey-connection">
                        <div class="connection-line"></div>
                        <div class="connection-type">${this.formatRelationType(rel.type)}</div>
                    </div>
                `;
            }
        });

        pathHTML += '</div>';
        this.pathContainer.innerHTML = pathHTML;

        // Add click handlers
        this.pathContainer.querySelectorAll('.journey-node').forEach(nodeEl => {
            nodeEl.addEventListener('click', (e) => {
                const nodeId = e.currentTarget.dataset.nodeId;
                const node = nodes.find(n => n.id === nodeId);
                if (node) {
                    this.selectNode(node);
                }
            });
        });
    }

    renderStats() {
        const stats = {
            'Path Length': this.journey.length,
            'Artists': this.journey.nodes.filter(n => n.type === 'Artist').length,
            'Releases': this.journey.nodes.filter(n => n.type === 'Release').length,
            'Labels': this.journey.nodes.filter(n => n.type === 'Label').length
        };

        let statsHTML = '<div class="stats-grid">';

        Object.entries(stats).forEach(([label, value]) => {
            statsHTML += `
                <div class="stat-item">
                    <div class="stat-value">${value}</div>
                    <div class="stat-label">${label}</div>
                </div>
            `;
        });

        statsHTML += '</div>';
        this.statsContainer.innerHTML = statsHTML;
    }

    renderTimeline() {
        // Extract years from nodes
        const yearsData = this.journey.nodes
            .filter(n => n.properties?.year)
            .map(n => ({
                year: n.properties.year,
                name: n.name,
                type: n.type
            }))
            .sort((a, b) => a.year - b.year);

        if (yearsData.length === 0) {
            this.timelineContainer.innerHTML = '<p class="text-muted">No timeline data available</p>';
            return;
        }

        const minYear = yearsData[0].year;
        const maxYear = yearsData[yearsData.length - 1].year;
        const yearRange = maxYear - minYear || 1;

        let timelineHTML = '<div class="timeline">';
        timelineHTML += '<div class="timeline-axis"></div>';

        yearsData.forEach(item => {
            const position = ((item.year - minYear) / yearRange) * 100;
            const icon = this.getNodeIcon(item.type);

            timelineHTML += `
                <div class="timeline-event" style="left: ${position}%">
                    <div class="timeline-marker">
                        <i class="fas ${icon}"></i>
                    </div>
                    <div class="timeline-label">
                        <div class="timeline-year">${item.year}</div>
                        <div class="timeline-name">${item.name}</div>
                    </div>
                </div>
            `;
        });

        // Add year markers
        timelineHTML += `
            <div class="timeline-years">
                <span class="year-start">${minYear}</span>
                <span class="year-end">${maxYear}</span>
            </div>
        `;

        timelineHTML += '</div>';
        this.timelineContainer.innerHTML = timelineHTML;
    }

    selectNode(node) {
        // Toggle selection
        const nodeEl = this.pathContainer.querySelector(`[data-node-id="${node.id}"]`);
        if (nodeEl) {
            nodeEl.classList.toggle('selected');

            const index = this.selectedNodes.findIndex(n => n.id === node.id);
            if (index >= 0) {
                this.selectedNodes.splice(index, 1);
            } else {
                this.selectedNodes.push(node);
            }

            // Emit event for main app
            if (window.playground && window.playground.handleNodeClick) {
                window.playground.handleNodeClick(node);
            }
        }
    }

    showNoJourney() {
        this.pathContainer.innerHTML = `
            <div class="no-journey">
                <i class="fas fa-route fa-3x text-muted mb-3"></i>
                <p class="text-muted">No journey found between the selected artists</p>
                <p class="text-muted small">Try selecting artists with more connections or increasing the search depth</p>
            </div>
        `;
        this.statsContainer.innerHTML = '';
        this.timelineContainer.innerHTML = '';
    }

    getNodeIcon(type) {
        const icons = {
            'Artist': 'fa-user',
            'Release': 'fa-compact-disc',
            'Label': 'fa-building',
            'Genre': 'fa-music'
        };
        return icons[type] || 'fa-circle';
    }

    formatRelationType(type) {
        // Convert relationship types to readable format
        const formatted = type.replace(/_/g, ' ').toLowerCase();
        return formatted.charAt(0).toUpperCase() + formatted.slice(1);
    }

    exportJourney() {
        if (!this.journey) {
            alert('No journey to export');
            return;
        }

        // Create journey data for export
        const exportData = {
            journey: this.journey,
            timestamp: new Date().toISOString(),
            metadata: {
                totalNodes: this.journey.nodes.length,
                pathLength: this.journey.length,
                relationships: this.journey.relationships.map(r => r.type)
            }
        };

        // Download as JSON
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `music-journey-${Date.now()}.json`;
        link.click();
        URL.revokeObjectURL(url);
    }

    reset() {
        this.journey = null;
        this.selectedNodes = [];
        this.pathContainer.innerHTML = '<p class="text-muted">Select start and end artists to find a journey</p>';
        this.statsContainer.innerHTML = '';
        this.timelineContainer.innerHTML = '';
    }
}
