// Music Industry Analytics Module

class AnalyticsModule {
    constructor() {
        this.currentChart = null;
        this.currentAnalysis = null;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.updateFormFields();
    }

    setupEventListeners() {
        const runAnalysisBtn = document.getElementById('runAnalysis');
        const analysisType = document.getElementById('analysisType');

        runAnalysisBtn.addEventListener('click', () => {
            this.runAnalysis();
        });

        analysisType.addEventListener('change', () => {
            this.updateFormFields();
        });

        // Handle enter key in input fields
        document.getElementById('artistAnalysisInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.runAnalysis();
            }
        });

        document.getElementById('labelAnalysisInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.runAnalysis();
            }
        });
    }

    updateFormFields() {
        const analysisType = document.getElementById('analysisType').value;
        const artistGroup = document.getElementById('artistAnalysisGroup');
        const labelGroup = document.getElementById('labelAnalysisGroup');

        // Show/hide relevant input groups
        artistGroup.style.display = analysisType === 'artist_evolution' ? 'block' : 'none';
        labelGroup.style.display = analysisType === 'label_insights' ? 'block' : 'none';

        // Update placeholders and help text
        this.updateHelpText(analysisType);
    }

    updateHelpText(analysisType) {
        const descriptions = {
            'genre_trends': 'Analyze how musical genres have evolved in popularity over time',
            'artist_evolution': 'Explore how an artist\'s musical style and collaborations have changed throughout their career',
            'label_insights': 'Examine record label market share, artist rosters, and industry influence',
            'market_analysis': 'Study music format adoption trends (vinyl, CD, digital) and regional patterns'
        };

        // Could add a description element to show this
        console.log(`Analysis type: ${descriptions[analysisType]}`);
    }

    async runAnalysis() {
        const analysisType = document.getElementById('analysisType').value;
        const timeRange = document.getElementById('timeRange').value;
        const artistName = document.getElementById('artistAnalysisInput').value.trim();
        const labelName = document.getElementById('labelAnalysisInput').value.trim();

        // Validate required fields
        if (analysisType === 'artist_evolution' && !artistName) {
            window.discoveryApp.showToast('Please enter an artist name for evolution analysis', 'error');
            return;
        }

        // Build request
        const request = {
            analysis_type: analysisType,
            limit: 20
        };

        // Add time range if provided
        if (timeRange) {
            const [startYear, endYear] = timeRange.split(',').map(Number);
            request.time_range = [startYear, endYear];
        }

        // Add specific parameters
        if (artistName) {
            request.artist_name = artistName;
        }

        if (labelName) {
            request.label_name = labelName;
        }

        try {
            const response = await window.discoveryApp.makeAPIRequest('analytics', request, 'POST');
            this.currentAnalysis = response;
            this.displayAnalytics(response);

            window.discoveryApp.showToast(
                `Analytics completed for ${analysisType.replace('_', ' ')}`,
                'success'
            );
        } catch (error) {
            console.error('Error running analytics:', error);
            this.displayError('Failed to run analytics. Please try again.');
        }
    }

    displayAnalytics(analysis) {
        this.displayChart(analysis);
        this.displayInsights(analysis);
    }

    displayChart(analysis) {
        const container = document.getElementById('analyticsChart');

        if (!analysis.chart_data || Object.keys(analysis.chart_data).length === 0) {
            container.innerHTML = this.createEmptyChartState();
            return;
        }

        // Clear previous chart
        container.innerHTML = '<div id="plotlyChart" style="width: 100%; height: 500px;"></div>';

        try {
            // Use Plotly to render the chart
            const plotlyData = analysis.chart_data.data || [];
            const plotlyLayout = analysis.chart_data.layout || {};

            // Customize layout for dark theme
            const darkLayout = {
                ...plotlyLayout,
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: {
                    color: '#ffffff',
                    family: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif'
                },
                colorway: [
                    '#667eea', '#764ba2', '#f093fb', '#4ecdc4',
                    '#45b7d1', '#f9ca24', '#f0932b', '#eb4d4b'
                ],
                xaxis: {
                    ...plotlyLayout.xaxis,
                    gridcolor: '#333',
                    color: '#ffffff'
                },
                yaxis: {
                    ...plotlyLayout.yaxis,
                    gridcolor: '#333',
                    color: '#ffffff'
                },
                legend: {
                    ...plotlyLayout.legend,
                    font: { color: '#ffffff' }
                }
            };

            Plotly.newPlot('plotlyChart', plotlyData, darkLayout, {
                responsive: true,
                displayModeBar: true,
                modeBarButtonsToRemove: ['pan2d', 'lasso2d', 'select2d'],
                displaylogo: false
            });

            this.currentChart = { data: plotlyData, layout: darkLayout };

        } catch (error) {
            console.error('Error rendering chart:', error);
            container.innerHTML = this.createChartErrorState(error.message);
        }
    }

    displayInsights(analysis) {
        const container = document.getElementById('analyticsInsights');
        const insights = analysis.insights || [];

        if (insights.length === 0) {
            container.innerHTML = '<p>No insights available for this analysis.</p>';
            return;
        }

        const html = `
            <div class="insights-header">
                <h3><i class="fas fa-lightbulb"></i> Key Insights</h3>
                <button class="btn btn-secondary btn-sm" onclick="window.analyticsModule.exportAnalysis()">
                    <i class="fas fa-download"></i> Export Analysis
                </button>
            </div>
            <ul class="insights-list">
                ${insights.map(insight => `<li>${this.sanitize(insight)}</li>`).join('')}
            </ul>
            <div class="metadata">
                <h4>Analysis Details</h4>
                <div class="metadata-grid">
                    ${this.formatMetadata(analysis.metadata)}
                </div>
            </div>
        `;

        container.innerHTML = html;
    }

    formatMetadata(metadata) {
        if (!metadata) return '<p>No metadata available</p>';

        const items = [];
        for (const [key, value] of Object.entries(metadata)) {
            const formattedKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            let formattedValue = value;

            if (Array.isArray(value)) {
                formattedValue = value.join(', ');
            } else if (typeof value === 'object') {
                formattedValue = JSON.stringify(value);
            }

            items.push(`
                <div class="metadata-item">
                    <span class="metadata-key">${formattedKey}:</span>
                    <span class="metadata-value">${this.sanitize(String(formattedValue))}</span>
                </div>
            `);
        }

        return items.join('');
    }

    createEmptyChartState() {
        return `
            <div class="empty-chart-state">
                <div class="empty-icon">
                    <i class="fas fa-chart-line" style="font-size: 4rem; color: var(--text-muted);"></i>
                </div>
                <h3>No Chart Data Available</h3>
                <p>The analysis did not return any data to visualize.</p>
                <div class="suggestions">
                    <ul>
                        <li>Try adjusting the time range</li>
                        <li>Check if the artist/label name is correct</li>
                        <li>Select a different analysis type</li>
                    </ul>
                </div>
            </div>
        `;
    }

    createChartErrorState(errorMessage) {
        return `
            <div class="chart-error-state">
                <div class="error-icon">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--error-color);"></i>
                </div>
                <h3>Chart Rendering Error</h3>
                <p>Failed to render the chart: ${this.sanitize(errorMessage)}</p>
                <button class="btn btn-primary" onclick="window.analyticsModule.runAnalysis()">
                    <i class="fas fa-redo"></i> Try Again
                </button>
            </div>
        `;
    }

    displayError(message) {
        const chartContainer = document.getElementById('analyticsChart');
        const insightsContainer = document.getElementById('analyticsInsights');

        const errorHtml = `
            <div class="error-state">
                <div class="error-icon">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--error-color);"></i>
                </div>
                <h3>Analysis Error</h3>
                <p>${this.sanitize(message)}</p>
                <button class="btn btn-primary" onclick="window.analyticsModule.runAnalysis()">
                    <i class="fas fa-redo"></i> Run Analysis Again
                </button>
            </div>
        `;

        chartContainer.innerHTML = errorHtml;
        insightsContainer.innerHTML = '';
    }

    sanitize(str) {
        if (!str) return '';
        const temp = document.createElement('div');
        temp.textContent = str;
        return temp.innerHTML;
    }

    // Export analysis data
    exportAnalysis() {
        if (!this.currentAnalysis) {
            window.discoveryApp.showToast('No analysis data to export', 'warning');
            return;
        }

        const data = {
            timestamp: new Date().toISOString(),
            analysis: this.currentAnalysis,
            chart_data: this.currentChart
        };

        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `music-analytics-${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        URL.revokeObjectURL(url);
        window.discoveryApp.showToast('Analysis exported successfully', 'success');
    }

    // Save chart as image
    saveChart() {
        if (!this.currentChart) {
            window.discoveryApp.showToast('No chart to save', 'warning');
            return;
        }

        Plotly.downloadImage('plotlyChart', {
            format: 'png',
            width: 1200,
            height: 800,
            filename: `music-analytics-chart-${new Date().toISOString().split('T')[0]}`
        });

        window.discoveryApp.showToast('Chart saved successfully', 'success');
    }
}

// Initialize the module
window.analyticsModule = new AnalyticsModule();

// Add CSS for analytics-specific styling
const analyticsStyle = document.createElement('style');
analyticsStyle.textContent = `
    .insights-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
        padding-bottom: 15px;
        border-bottom: 1px solid var(--border-color);
    }

    .insights-header h3 {
        color: var(--primary-color);
        margin: 0;
    }

    .metadata {
        margin-top: 30px;
        padding-top: 20px;
        border-top: 1px solid var(--border-color);
    }

    .metadata h4 {
        color: var(--secondary-color);
        margin-bottom: 15px;
    }

    .metadata-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 15px;
    }

    .metadata-item {
        background: var(--dark-bg);
        padding: 12px;
        border-radius: var(--radius);
        border-left: 3px solid var(--primary-color);
    }

    .metadata-key {
        font-weight: bold;
        color: var(--primary-color);
        display: block;
        margin-bottom: 4px;
    }

    .metadata-value {
        color: var(--text-light);
        word-break: break-word;
    }

    .empty-chart-state, .chart-error-state {
        text-align: center;
        padding: 80px 20px;
        color: var(--text-muted);
    }

    .empty-chart-state h3, .chart-error-state h3 {
        margin: 20px 0;
        color: var(--text-light);
    }

    .suggestions {
        margin-top: 20px;
        text-align: left;
        max-width: 300px;
        margin-left: auto;
        margin-right: auto;
    }

    .suggestions ul {
        list-style-position: inside;
    }

    .suggestions li {
        margin: 8px 0;
    }

    #artistAnalysisGroup, #labelAnalysisGroup {
        transition: all 0.3s ease;
    }

    .plotly-container {
        border-radius: var(--radius);
        overflow: hidden;
    }
`;
document.head.appendChild(analyticsStyle);
