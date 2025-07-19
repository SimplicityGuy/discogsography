// Trend Analysis Visualization using D3.js

class TrendAnalysis {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.margin = { top: 20, right: 120, bottom: 50, left: 60 };
        this.width = 800 - this.margin.left - this.margin.right;
        this.height = 400 - this.margin.top - this.margin.bottom;
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
        this.svg.append('text')
            .attr('x', (this.width + this.margin.left + this.margin.right) / 2)
            .attr('y', 15)
            .attr('text-anchor', 'middle')
            .style('font-size', '16px')
            .style('font-weight', 'bold')
            .text('Music Trends Over Time');

        // Initialize scales
        this.xScale = d3.scaleLinear().range([0, this.width]);
        this.yScale = d3.scaleLinear().range([this.height, 0]);
        this.colorScale = d3.scaleOrdinal(d3.schemeCategory10);

        // Initialize axes
        this.xAxis = d3.axisBottom(this.xScale).tickFormat(d3.format('d'));
        this.yAxis = d3.axisLeft(this.yScale);

        // Add axes groups
        this.xAxisGroup = this.g.append('g')
            .attr('class', 'x-axis')
            .attr('transform', `translate(0,${this.height})`);

        this.yAxisGroup = this.g.append('g')
            .attr('class', 'y-axis');

        // Add axis labels
        this.svg.append('text')
            .attr('transform', 'rotate(-90)')
            .attr('y', 0)
            .attr('x', 0 - (this.height / 2))
            .attr('dy', '1em')
            .style('text-anchor', 'middle')
            .text('Count');

        this.svg.append('text')
            .attr('transform', `translate(${(this.width / 2) + this.margin.left}, ${this.height + this.margin.top + 40})`)
            .style('text-anchor', 'middle')
            .text('Year');

        // Add tooltip
        this.tooltip = d3.select('body').append('div')
            .attr('class', 'chart-tooltip')
            .style('opacity', 0)
            .style('position', 'absolute')
            .style('background', 'rgba(0, 0, 0, 0.8)')
            .style('color', 'white')
            .style('padding', '8px')
            .style('border-radius', '4px')
            .style('font-size', '12px')
            .style('pointer-events', 'none');

        // Handle window resize
        window.addEventListener('resize', () => this.handleResize());
    }

    render(trendData) {
        if (!trendData || !trendData.trends) {
            this.showNoData();
            return;
        }

        this.data = trendData;
        const trendType = trendData.type;

        // Process data for visualization
        const processedData = this.processData(trendData.trends);

        // Update scales
        this.xScale.domain(d3.extent(processedData.years));
        this.yScale.domain([0, d3.max(processedData.maxValues)]);

        // Update axes
        this.xAxisGroup.transition().duration(500).call(this.xAxis);
        this.yAxisGroup.transition().duration(500).call(this.yAxis);

        // Clear previous visualization
        this.g.selectAll('.trend-line').remove();
        this.g.selectAll('.trend-area').remove();
        this.g.selectAll('.legend').remove();

        // Create line generator
        const line = d3.line()
            .x(d => this.xScale(d.year))
            .y(d => this.yScale(d.value))
            .curve(d3.curveMonotoneX);

        // Create area generator for stacked area chart
        const area = d3.area()
            .x(d => this.xScale(d.year))
            .y0(d => this.yScale(d.y0))
            .y1(d => this.yScale(d.y1))
            .curve(d3.curveMonotoneX);

        // Render based on trend type
        if (trendType === 'genre') {
            this.renderStackedArea(processedData, area);
        } else {
            this.renderMultiLine(processedData, line);
        }

        // Add legend
        this.addLegend(processedData.categories);
    }

    processData(trends) {
        const categories = new Set();
        const years = trends.map(t => t.year);
        const dataByCategory = {};

        // Extract all categories and organize data
        trends.forEach(yearData => {
            yearData.data.forEach(item => {
                const category = item.genre || item.artist || item.label;
                if (category) {
                    categories.add(category);
                    if (!dataByCategory[category]) {
                        dataByCategory[category] = [];
                    }
                    dataByCategory[category].push({
                        year: yearData.year,
                        value: item.count || item.releases || 0,
                        category: category
                    });
                }
            });
        });

        // Fill missing years with 0
        const allCategories = Array.from(categories);
        allCategories.forEach(category => {
            const existingYears = new Set(dataByCategory[category].map(d => d.year));
            years.forEach(year => {
                if (!existingYears.has(year)) {
                    dataByCategory[category].push({
                        year: year,
                        value: 0,
                        category: category
                    });
                }
            });
            dataByCategory[category].sort((a, b) => a.year - b.year);
        });

        // Calculate max values for scale
        const maxValues = years.map(year => {
            let sum = 0;
            allCategories.forEach(category => {
                const data = dataByCategory[category].find(d => d.year === year);
                if (data) sum += data.value;
            });
            return sum;
        });

        return {
            categories: allCategories,
            dataByCategory: dataByCategory,
            years: years,
            maxValues: maxValues
        };
    }

    renderMultiLine(processedData, line) {
        const { categories, dataByCategory } = processedData;

        categories.forEach((category, i) => {
            const data = dataByCategory[category];

            // Add line
            this.g.append('path')
                .datum(data)
                .attr('class', 'trend-line')
                .attr('fill', 'none')
                .attr('stroke', this.colorScale(i))
                .attr('stroke-width', 2)
                .attr('d', line)
                .style('opacity', 0)
                .transition()
                .duration(1000)
                .style('opacity', 1);

            // Add dots
            this.g.selectAll(`.dot-${i}`)
                .data(data)
                .enter().append('circle')
                .attr('class', `dot-${i}`)
                .attr('cx', d => this.xScale(d.year))
                .attr('cy', d => this.yScale(d.value))
                .attr('r', 0)
                .attr('fill', this.colorScale(i))
                .on('mouseover', (event, d) => this.showTooltip(event, d))
                .on('mouseout', () => this.hideTooltip())
                .transition()
                .duration(1000)
                .attr('r', 4);
        });
    }

    renderStackedArea(processedData, area) {
        const { categories, dataByCategory, years } = processedData;

        // Create stacked data
        const stackedData = [];
        years.forEach(year => {
            let y0 = 0;
            categories.forEach((category, i) => {
                const data = dataByCategory[category].find(d => d.year === year) || { value: 0 };
                const y1 = y0 + data.value;
                stackedData.push({
                    year: year,
                    category: category,
                    y0: y0,
                    y1: y1,
                    value: data.value
                });
                y0 = y1;
            });
        });

        // Group by category
        const groupedData = d3.group(stackedData, d => d.category);

        // Render areas
        Array.from(groupedData.entries()).forEach(([category, data], i) => {
            this.g.append('path')
                .datum(data)
                .attr('class', 'trend-area')
                .attr('fill', this.colorScale(i))
                .attr('fill-opacity', 0.7)
                .attr('stroke', this.colorScale(i))
                .attr('stroke-width', 1)
                .attr('d', area)
                .on('mouseover', (event) => this.highlightCategory(category))
                .on('mouseout', () => this.resetHighlight())
                .style('opacity', 0)
                .transition()
                .duration(1000)
                .style('opacity', 1);
        });
    }

    addLegend(categories) {
        const legend = this.g.append('g')
            .attr('class', 'legend')
            .attr('transform', `translate(${this.width + 10}, 20)`);

        const legendItems = legend.selectAll('.legend-item')
            .data(categories.slice(0, 10)) // Limit to top 10
            .enter().append('g')
            .attr('class', 'legend-item')
            .attr('transform', (d, i) => `translate(0, ${i * 20})`);

        legendItems.append('rect')
            .attr('width', 12)
            .attr('height', 12)
            .attr('fill', (d, i) => this.colorScale(i))
            .attr('fill-opacity', 0.7);

        legendItems.append('text')
            .attr('x', 18)
            .attr('y', 9)
            .attr('dy', '0.32em')
            .style('font-size', '12px')
            .text(d => d.length > 15 ? d.substring(0, 15) + '...' : d);
    }

    showTooltip(event, d) {
        this.tooltip.transition().duration(200).style('opacity', .9);
        this.tooltip.html(`
            <strong>${d.category}</strong><br/>
            Year: ${d.year}<br/>
            Value: ${d.value}
        `)
            .style('left', (event.pageX + 10) + 'px')
            .style('top', (event.pageY - 28) + 'px');
    }

    hideTooltip() {
        this.tooltip.transition().duration(500).style('opacity', 0);
    }

    highlightCategory(category) {
        // Dim all other areas
        this.g.selectAll('.trend-area')
            .style('opacity', d => d[0].category === category ? 1 : 0.2);
    }

    resetHighlight() {
        this.g.selectAll('.trend-area')
            .style('opacity', 0.7);
    }

    showNoData() {
        this.g.selectAll('*').remove();
        this.g.append('text')
            .attr('x', this.width / 2)
            .attr('y', this.height / 2)
            .attr('text-anchor', 'middle')
            .style('font-size', '16px')
            .style('fill', '#666')
            .text('No trend data available');
    }

    handleResize() {
        // Update dimensions based on container
        const container = this.container.parentElement;
        if (container) {
            this.width = container.clientWidth - this.margin.left - this.margin.right;
            this.svg.attr('width', this.width + this.margin.left + this.margin.right);

            // Update scales and re-render
            this.xScale.range([0, this.width]);
            if (this.data) {
                this.render(this.data);
            }
        }
    }

    reset() {
        this.data = null;
        this.g.selectAll('*').remove();
        this.showNoData();
    }
}
