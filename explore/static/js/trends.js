/**
 * Plotly.js time-series chart for release trends.
 */
class TrendsChart {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.placeholder = document.getElementById('trendsPlaceholder');
        this.hasData = false;
    }

    /**
     * Render trends data.
     * @param {Object} data - Trends response { name, type, data: [{year, count}] }
     */
    render(data) {
        if (!data || !data.data || data.data.length === 0) {
            this.clear();
            return;
        }

        this.placeholder.classList.add('hidden');
        this.hasData = true;

        const years = data.data.map(d => d.year);
        const counts = data.data.map(d => d.count);

        // Pad x-axis range
        const minYear = Math.min(...years) - 3;
        const maxYear = Math.max(...years) + 3;

        const trace = {
            x: years,
            y: counts,
            type: 'scatter',
            mode: 'lines+markers',
            name: `${data.name} releases`,
            line: {
                color: '#1877f2',
                width: 2,
            },
            marker: {
                color: '#1877f2',
                size: 6,
            },
            fill: 'tozeroy',
            fillcolor: 'rgba(24, 119, 242, 0.1)',
        };

        const layout = {
            title: {
                text: `Release Timeline: ${data.name}`,
                font: { color: '#e4e6eb', size: 18 },
            },
            xaxis: {
                title: { text: 'Year', font: { color: '#b0b3b8' } },
                range: [minYear, maxYear],
                tickfont: { color: '#b0b3b8' },
                gridcolor: '#2d3051',
                linecolor: '#2d3051',
            },
            yaxis: {
                title: { text: 'Number of Releases', font: { color: '#b0b3b8' } },
                tickfont: { color: '#b0b3b8' },
                gridcolor: '#2d3051',
                linecolor: '#2d3051',
                rangemode: 'tozero',
            },
            plot_bgcolor: '#0a0e27',
            paper_bgcolor: '#0a0e27',
            font: { color: '#e4e6eb' },
            margin: { t: 60, r: 30, b: 60, l: 60 },
            hovermode: 'x unified',
        };

        const config = {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        };

        Plotly.newPlot(this.container, [trace], layout, config);
    }

    clear() {
        Plotly.purge(this.container);
        this.placeholder.classList.remove('hidden');
        this.hasData = false;
    }
}
