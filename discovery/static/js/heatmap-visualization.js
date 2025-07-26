// Heatmap Visualization using D3.js

class HeatmapVisualization {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.margin = { top: 80, right: 50, bottom: 100, left: 100 };
        this.width = 600 - this.margin.left - this.margin.right;
        this.height = 600 - this.margin.top - this.margin.bottom;
        this.svg = null;
        this.data = null;

        this.init();
    }

    init() {
        // Create SVG container
        this.svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', this.width + this.margin.left + this.margin.right)
            .attr('height', this.height + this.margin.top + this.margin.bottom);

        this.g = this.svg.append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        // Add title
        this.titleText = this.svg.append('text')
            .attr('x', (this.width + this.margin.left + this.margin.right) / 2)
            .attr('y', 30)
            .attr('text-anchor', 'middle')
            .style('font-size', '18px')
            .style('font-weight', 'bold');

        // Initialize scales
        this.xScale = d3.scaleBand().range([0, this.width]).padding(0.05);
        this.yScale = d3.scaleBand().range([this.height, 0]).padding(0.05);

        // Color scale - using a diverging color scheme
        this.colorScale = d3.scaleSequential()
            .interpolator(d3.interpolateRdYlBu)
            .domain([0, 1]);

        // Add tooltip
        this.tooltip = d3.select('body').append('div')
            .attr('class', 'heatmap-tooltip')
            .style('opacity', 0)
            .style('position', 'absolute')
            .style('background', 'rgba(0, 0, 0, 0.9)')
            .style('color', 'white')
            .style('padding', '10px')
            .style('border-radius', '5px')
            .style('font-size', '12px')
            .style('pointer-events', 'none')
            .style('z-index', '1000');

        // Add axes groups
        this.xAxisGroup = this.g.append('g')
            .attr('class', 'x-axis')
            .attr('transform', `translate(0,${this.height})`);

        this.yAxisGroup = this.g.append('g')
            .attr('class', 'y-axis');

        // Add legend group
        this.legendGroup = this.svg.append('g')
            .attr('class', 'legend')
            .attr('transform', `translate(${this.width + this.margin.left + 10}, ${this.margin.top})`);

        // Handle window resize
        window.addEventListener('resize', () => this.handleResize());
    }

    render(heatmapData) {
        if (!heatmapData || !heatmapData.heatmap || heatmapData.heatmap.length === 0) {
            this.showNoData();
            return;
        }

        this.data = heatmapData;
        const { heatmap, labels, type } = heatmapData;

        // Update title based on type
        const titles = {
            'genre': 'Artist Genre Similarity',
            'collab': 'Artist Collaboration Network',
            'style': 'Musical Style Connections'
        };
        this.titleText.text(titles[type] || 'Similarity Heatmap');

        // Process data to create full matrix
        const matrix = this.createMatrix(heatmap, labels);

        // Update scales
        this.xScale.domain(labels);
        this.yScale.domain(labels);

        // Find min and max values for color scale
        const values = heatmap.map(d => d.value);
        const maxValue = d3.max(values) || 1;
        this.colorScale.domain([0, maxValue]);

        // Clear previous visualization
        this.g.selectAll('.heatmap-cell').remove();

        // Create cells
        const cells = this.g.selectAll('.heatmap-cell')
            .data(matrix)
            .enter().append('g')
            .attr('class', 'heatmap-cell');

        cells.append('rect')
            .attr('x', d => this.xScale(d.x))
            .attr('y', d => this.yScale(d.y))
            .attr('width', this.xScale.bandwidth())
            .attr('height', this.yScale.bandwidth())
            .attr('fill', d => d.value > 0 ? this.colorScale(d.value) : '#f0f0f0')
            .attr('stroke', '#fff')
            .attr('stroke-width', 1)
            .style('opacity', 0)
            .on('mouseover', (event, d) => this.showTooltip(event, d))
            .on('mouseout', () => this.hideTooltip())
            .on('click', (event, d) => this.handleCellClick(d))
            .transition()
            .duration(800)
            .delay((d, i) => i * 2)
            .style('opacity', 1);

        // Update axes
        this.updateAxes(labels);

        // Add legend
        this.addLegend(maxValue);

        // Add value labels for small matrices
        if (labels.length <= 15) {
            this.addValueLabels(cells);
        }
    }

    createMatrix(heatmapData, labels) {
        const matrix = [];
        const dataMap = new Map();

        // Create a map for quick lookup
        heatmapData.forEach(d => {
            const key1 = `${d.x}-${d.y}`;
            const key2 = `${d.y}-${d.x}`;
            dataMap.set(key1, d.value);
            dataMap.set(key2, d.value); // Make it symmetric
        });

        // Create full matrix
        labels.forEach(x => {
            labels.forEach(y => {
                const key = `${x}-${y}`;
                const value = dataMap.get(key) || (x === y ? 0 : 0);
                matrix.push({ x, y, value });
            });
        });

        return matrix;
    }

    updateAxes(labels) {
        // X-axis
        this.xAxisGroup
            .transition()
            .duration(500)
            .call(d3.axisBottom(this.xScale))
            .selectAll('text')
            .style('text-anchor', 'end')
            .attr('dx', '-.8em')
            .attr('dy', '.15em')
            .attr('transform', 'rotate(-45)')
            .text(d => d.length > 20 ? d.substring(0, 20) + '...' : d);

        // Y-axis
        this.yAxisGroup
            .transition()
            .duration(500)
            .call(d3.axisLeft(this.yScale))
            .selectAll('text')
            .text(d => d.length > 20 ? d.substring(0, 20) + '...' : d);
    }

    addLegend(maxValue) {
        this.legendGroup.selectAll('*').remove();

        const legendHeight = 200;
        const legendWidth = 20;

        // Create gradient
        const gradient = this.legendGroup.append('defs')
            .append('linearGradient')
            .attr('id', 'heatmap-gradient')
            .attr('x1', '0%')
            .attr('y1', '100%')
            .attr('x2', '0%')
            .attr('y2', '0%');

        // Add gradient stops
        const nStops = 10;
        for (let i = 0; i <= nStops; i++) {
            const offset = i / nStops;
            gradient.append('stop')
                .attr('offset', `${offset * 100}%`)
                .attr('stop-color', this.colorScale(offset * maxValue));
        }

        // Add legend rectangle
        this.legendGroup.append('rect')
            .attr('width', legendWidth)
            .attr('height', legendHeight)
            .style('fill', 'url(#heatmap-gradient)');

        // Add legend scale
        const legendScale = d3.scaleLinear()
            .domain([0, maxValue])
            .range([legendHeight, 0]);

        const legendAxis = d3.axisRight(legendScale)
            .ticks(5)
            .tickFormat(d3.format('.0f'));

        this.legendGroup.append('g')
            .attr('transform', `translate(${legendWidth}, 0)`)
            .call(legendAxis);

        // Add legend title
        this.legendGroup.append('text')
            .attr('x', legendWidth / 2)
            .attr('y', -10)
            .attr('text-anchor', 'middle')
            .style('font-size', '12px')
            .text('Value');
    }

    addValueLabels(cells) {
        cells.append('text')
            .attr('x', d => this.xScale(d.x) + this.xScale.bandwidth() / 2)
            .attr('y', d => this.yScale(d.y) + this.yScale.bandwidth() / 2)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .style('font-size', '10px')
            .style('fill', d => {
                const value = d.value / d3.max(this.data.heatmap, h => h.value);
                return value > 0.5 ? 'white' : 'black';
            })
            .style('opacity', 0)
            .text(d => d.value > 0 ? d.value : '')
            .transition()
            .duration(800)
            .delay((d, i) => i * 2)
            .style('opacity', d => d.value > 0 ? 1 : 0);
    }

    showTooltip(event, d) {
        if (d.value === 0) return;

        const tooltipText = this.getTooltipText(d);

        this.tooltip.transition().duration(200).style('opacity', .9);
        this.tooltip.html(tooltipText)
            .style('left', (event.pageX + 10) + 'px')
            .style('top', (event.pageY - 28) + 'px');
    }

    getTooltipText(d) {
        let text = `<strong>${d.x}</strong> ↔ <strong>${d.y}</strong><br/>`;

        switch (this.data.type) {
            case 'genre':
                text += `Shared Genres: ${d.value}`;
                break;
            case 'collab':
                text += d.value > 0 ? 'Collaborated' : 'No Collaboration';
                break;
            case 'style':
                text += `Style Similarity: ${d.value}`;
                break;
            default:
                text += `Value: ${d.value}`;
        }

        return text;
    }

    hideTooltip() {
        this.tooltip.transition().duration(500).style('opacity', 0);
    }

    handleCellClick(d) {
        if (d.value === 0 || d.x === d.y) return;

        // Emit event for main app
        if (window.playground) {
            window.playground.showNotification(`Selected: ${d.x} ↔ ${d.y}`, 'info');

            // Could trigger a journey search between these artists
            if (this.data.type === 'collab' || this.data.type === 'genre') {
                // Auto-fill journey builder
                document.getElementById('startArtist').value = d.x;
                document.getElementById('endArtist').value = d.y;
            }
        }
    }

    showNoData() {
        this.g.selectAll('*').remove();
        this.legendGroup.selectAll('*').remove();

        this.g.append('text')
            .attr('x', this.width / 2)
            .attr('y', this.height / 2)
            .attr('text-anchor', 'middle')
            .style('font-size', '16px')
            .style('fill', '#666')
            .text('No heatmap data available');
    }

    handleResize() {
        // Update dimensions based on container
        const container = this.container.parentElement;
        if (container) {
            const size = Math.min(container.clientWidth, container.clientHeight) - 200;
            this.width = size;
            this.height = size;

            this.svg
                .attr('width', this.width + this.margin.left + this.margin.right)
                .attr('height', this.height + this.margin.top + this.margin.bottom);

            // Update scales and re-render
            this.xScale.range([0, this.width]);
            this.yScale.range([this.height, 0]);

            if (this.data) {
                this.render(this.data);
            }
        }
    }

    reset() {
        this.data = null;
        this.g.selectAll('*').remove();
        this.legendGroup.selectAll('*').remove();
        this.showNoData();
    }
}
