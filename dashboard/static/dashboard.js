// Dashboard JavaScript
class Dashboard {
    constructor() {
        this.ws = null;
        this.reconnectInterval = null;
        this.activityLog = [];
        this.maxLogEntries = 50;
        this.queueChart = null;
        this.queueChartData = {
            labels: [],
            datasets: []
        };
        // Track historical rate data for 5-minute windows
        this.rateHistory = new Map(); // Map<queueName, {publish: [], ack: []}>
        this.historyWindowMs = 5 * 60 * 1000; // 5 minutes

        this.initializeWebSocket();
        this.initializeChart();
        this.fetchInitialData();
    }

    initializeWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.updateConnectionStatus('connected');
            this.addLogEntry('Connected to dashboard');

            // Clear reconnect interval if it exists
            if (this.reconnectInterval) {
                clearInterval(this.reconnectInterval);
                this.reconnectInterval = null;
            }
        };

        this.ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (message.type === 'metrics_update') {
                this.updateDashboard(message.data);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.updateConnectionStatus('disconnected');
            this.addLogEntry('Connection error', 'error');
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.updateConnectionStatus('disconnected');
            this.addLogEntry('Disconnected from dashboard', 'warning');
            this.reconnect();
        };
    }

    reconnect() {
        if (!this.reconnectInterval) {
            this.reconnectInterval = setInterval(() => {
                console.log('Attempting to reconnect...');
                this.initializeWebSocket();
            }, 5000);
        }
    }

    updateConnectionStatus(status) {
        const indicator = document.querySelector('.status-indicator');
        const text = document.querySelector('.status-text');

        indicator.className = `status-indicator ${status}`;
        text.textContent = status === 'connected' ? 'Connected' : 'Disconnected';
    }

    async fetchInitialData() {
        try {
            const response = await fetch('/api/metrics');
            if (response.ok) {
                const data = await response.json();
                this.updateDashboard(data);
            }
        } catch (error) {
            console.error('Error fetching initial data:', error);
            this.addLogEntry('Failed to fetch initial data', 'error');
        }
    }

    updateDashboard(data) {
        this.updateServices(data.services);
        this.updateQueues(data.queues);
        this.updateDatabases(data.databases);
        this.updateLastUpdated(data.timestamp);
    }

    updateServices(services) {
        const container = document.getElementById('servicesGrid');
        container.innerHTML = '';

        services.forEach(service => {
            const card = this.createServiceCard(service);
            container.appendChild(card);
        });
    }

    createServiceCard(service) {
        const card = document.createElement('div');
        card.className = 'service-card';

        const statusClass = service.status.toLowerCase();
        const progressHtml = service.progress !== null ? `
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${service.progress * 100}%"></div>
            </div>
        ` : '';

        const taskHtml = service.current_task ? `
            <div class="service-task">
                <strong>Current Task:</strong> ${service.current_task}
                ${progressHtml}
            </div>
        ` : '';

        card.innerHTML = `
            <div class="service-header">
                <span class="service-name">${service.name}</span>
                <span class="service-status ${statusClass}">${service.status}</span>
            </div>
            <div class="service-details">
                ${service.last_seen ? `Last seen: ${this.formatTime(service.last_seen)}` : 'Never seen'}
                ${service.error ? `<br><span style="color: var(--accent-red)">Error: ${service.error}</span>` : ''}
            </div>
            ${taskHtml}
        `;

        return card;
    }

    updateRateHistory(queueName, publishRate, ackRate) {
        const now = Date.now();

        if (!this.rateHistory.has(queueName)) {
            this.rateHistory.set(queueName, { publish: [], ack: [] });
        }

        const history = this.rateHistory.get(queueName);

        // Add new data points
        history.publish.push({ timestamp: now, value: publishRate });
        history.ack.push({ timestamp: now, value: ackRate });

        // Remove data older than 5 minutes
        const cutoff = now - this.historyWindowMs;
        history.publish = history.publish.filter(d => d.timestamp >= cutoff);
        history.ack = history.ack.filter(d => d.timestamp >= cutoff);
    }

    getRateRange(queueName, type) {
        if (!this.rateHistory.has(queueName)) {
            return { min: 0, max: 0, current: 0 };
        }

        const history = this.rateHistory.get(queueName);
        const data = history[type];

        if (data.length === 0) {
            return { min: 0, max: 0, current: 0 };
        }

        const values = data.map(d => d.value);
        const current = values[values.length - 1];
        const min = Math.min(...values);
        const max = Math.max(...values);

        return { min, max, current };
    }

    updateQueues(queues) {
        const container = document.getElementById('queuesGrid');
        container.innerHTML = '';

        // Update chart data
        const labels = [];
        const messagesData = [];
        const rateRanges = [];

        queues.forEach(queue => {
            const card = this.createQueueCard(queue);
            container.appendChild(card);

            const shortName = queue.name.replace('discogsography-', '');

            // Update historical data
            this.updateRateHistory(shortName, queue.message_rate, queue.ack_rate);

            // Collect data for chart
            labels.push(shortName);
            messagesData.push(queue.messages);

            const publishRange = this.getRateRange(shortName, 'publish');
            const ackRange = this.getRateRange(shortName, 'ack');

            rateRanges.push({
                queue: shortName,
                publish: publishRange,
                ack: ackRange
            });
        });

        // Update chart
        this.updateQueueChart(labels, messagesData, rateRanges);

        // Log significant queue changes
        queues.forEach(queue => {
            if (queue.messages > 1000) {
                this.addLogEntry(`High message count in ${queue.name}: ${queue.messages}`, 'warning');
            }
        });
    }

    createQueueCard(queue) {
        const card = document.createElement('div');
        card.className = 'queue-card';

        const shortName = queue.name.replace('discogsography-', '');

        card.innerHTML = `
            <div class="queue-header">
                <span class="queue-name">${shortName}</span>
                <span class="queue-consumers">${queue.consumers} consumers</span>
            </div>
            <div class="queue-stats">
                <div class="stat-item">
                    <span class="stat-label">Total:</span>
                    <span class="stat-value">${queue.messages.toLocaleString()}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Ready:</span>
                    <span class="stat-value">${queue.messages_ready.toLocaleString()}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Unacked:</span>
                    <span class="stat-value">${queue.messages_unacknowledged.toLocaleString()}</span>
                </div>
            </div>
            <div class="queue-rates">
                <div class="rate-item">
                    <div class="rate-label">Publish Rate</div>
                    <div class="rate-value">${queue.message_rate.toFixed(1)}/s</div>
                </div>
                <div class="rate-item">
                    <div class="rate-label">Ack Rate</div>
                    <div class="rate-value">${queue.ack_rate.toFixed(1)}/s</div>
                </div>
            </div>
        `;

        return card;
    }

    updateDatabases(databases) {
        const container = document.getElementById('databasesGrid');
        container.innerHTML = '';

        databases.forEach(database => {
            const card = this.createDatabaseCard(database);
            container.appendChild(card);
        });
    }

    createDatabaseCard(database) {
        const card = document.createElement('div');
        card.className = 'database-card';

        const statusClass = database.status.toLowerCase();

        card.innerHTML = `
            <div class="database-header">
                <span class="database-name">${database.name}</span>
                <span class="service-status ${statusClass}">${database.status}</span>
            </div>
            <div class="database-stats">
                <div class="database-stat">
                    <span>Connections:</span>
                    <span>${database.connection_count}</span>
                </div>
                ${database.size ? `
                    <div class="database-stat">
                        <span>Size:</span>
                        <span>${database.size}</span>
                    </div>
                ` : ''}
                ${database.error ? `
                    <div class="database-stat" style="color: var(--accent-red)">
                        <span>Error:</span>
                        <span>${database.error}</span>
                    </div>
                ` : ''}
            </div>
        `;

        return card;
    }

    initializeChart() {
        const ctx = document.getElementById('queueChart').getContext('2d');

        // Custom plugin to draw range bars
        const rangeBarPlugin = {
            id: 'rangeBar',
            afterDatasetsDraw: (chart) => {
                const ctx = chart.ctx;
                const xScale = chart.scales.x;
                const yScale = chart.scales['y-rate'];

                const publishRangeData = chart.data.datasets[1].data;
                const ackRangeData = chart.data.datasets[3].data;

                if (!publishRangeData || publishRangeData.length === 0) return;

                const barWidth = 12;
                const halfWidth = barWidth / 2;

                // Draw publish ranges
                publishRangeData.forEach((data, index) => {
                    if (!data || data.length !== 2) return;

                    const xPos = xScale.getPixelForValue(index) - 8; // Offset left
                    const yMin = yScale.getPixelForValue(data[0]);
                    const yMax = yScale.getPixelForValue(data[1]);
                    const height = yMin - yMax;

                    if (height < 1) {
                        // Draw a line when min == max
                        ctx.save();
                        ctx.strokeStyle = 'rgba(66, 184, 131, 1)';
                        ctx.lineWidth = 2;
                        ctx.beginPath();
                        ctx.moveTo(xPos - halfWidth, yMin);
                        ctx.lineTo(xPos + halfWidth, yMin);
                        ctx.stroke();
                        ctx.restore();
                    } else {
                        // Draw a bar
                        ctx.save();
                        ctx.fillStyle = 'rgba(66, 184, 131, 0.3)';
                        ctx.strokeStyle = 'rgba(66, 184, 131, 1)';
                        ctx.lineWidth = 1;
                        ctx.fillRect(xPos - halfWidth, yMax, barWidth, height);
                        ctx.strokeRect(xPos - halfWidth, yMax, barWidth, height);
                        ctx.restore();
                    }
                });

                // Draw ack ranges
                ackRangeData.forEach((data, index) => {
                    if (!data || data.length !== 2) return;

                    const xPos = xScale.getPixelForValue(index) + 8; // Offset right
                    const yMin = yScale.getPixelForValue(data[0]);
                    const yMax = yScale.getPixelForValue(data[1]);
                    const height = yMin - yMax;

                    if (height < 1) {
                        // Draw a line when min == max
                        ctx.save();
                        ctx.strokeStyle = 'rgba(255, 159, 64, 1)';
                        ctx.lineWidth = 2;
                        ctx.beginPath();
                        ctx.moveTo(xPos - halfWidth, yMin);
                        ctx.lineTo(xPos + halfWidth, yMin);
                        ctx.stroke();
                        ctx.restore();
                    } else {
                        // Draw a bar
                        ctx.save();
                        ctx.fillStyle = 'rgba(255, 159, 64, 0.3)';
                        ctx.strokeStyle = 'rgba(255, 159, 64, 1)';
                        ctx.lineWidth = 1;
                        ctx.fillRect(xPos - halfWidth, yMax, barWidth, height);
                        ctx.strokeRect(xPos - halfWidth, yMax, barWidth, height);
                        ctx.restore();
                    }
                });
            }
        };

        this.queueChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Messages',
                        data: [],
                        backgroundColor: 'rgba(24, 119, 242, 0.6)',
                        borderColor: 'rgba(24, 119, 242, 1)',
                        borderWidth: 1,
                        yAxisID: 'y-messages',
                        order: 1
                    },
                    {
                        label: 'Publish Range (hidden)',
                        data: [],
                        type: 'scatter',
                        backgroundColor: 'transparent',
                        borderColor: 'transparent',
                        pointRadius: 0,
                        yAxisID: 'y-rate',
                        order: 3
                    },
                    {
                        label: 'Publish Current',
                        data: [],
                        type: 'scatter',
                        backgroundColor: 'rgba(66, 184, 131, 1)',
                        borderColor: 'rgba(255, 255, 255, 0.8)',
                        borderWidth: 2,
                        pointRadius: 6,
                        pointHoverRadius: 8,
                        yAxisID: 'y-rate',
                        order: 2
                    },
                    {
                        label: 'Ack Range (hidden)',
                        data: [],
                        type: 'scatter',
                        backgroundColor: 'transparent',
                        borderColor: 'transparent',
                        pointRadius: 0,
                        yAxisID: 'y-rate',
                        order: 3
                    },
                    {
                        label: 'Ack Current',
                        data: [],
                        type: 'scatter',
                        backgroundColor: 'rgba(255, 159, 64, 1)',
                        borderColor: 'rgba(255, 255, 255, 0.8)',
                        borderWidth: 2,
                        pointRadius: 6,
                        pointHoverRadius: 8,
                        yAxisID: 'y-rate',
                        order: 2
                    }
                ]
            },
            plugins: [rangeBarPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        labels: {
                            color: '#e4e6eb',
                            filter: (item) => !item.text.includes('Range')
                        }
                    },
                    title: {
                        display: true,
                        text: 'Queue Statistics (Ranges show 5-min history)',
                        color: '#e4e6eb'
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.dataset.label || '';
                                if (label.includes('Range')) {
                                    const range = context.raw;
                                    return `${label}: ${range[0].toFixed(1)} - ${range[1].toFixed(1)} msg/s`;
                                } else if (label.includes('Current')) {
                                    return `${label}: ${context.parsed.y.toFixed(1)} msg/s`;
                                } else {
                                    return `${label}: ${context.parsed.y.toLocaleString()}`;
                                }
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            color: '#b0b3b8'
                        },
                        grid: {
                            color: 'rgba(45, 48, 81, 0.5)'
                        }
                    },
                    'y-messages': {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: {
                            display: true,
                            text: 'Messages in Queue',
                            color: '#b0b3b8'
                        },
                        ticks: {
                            color: '#b0b3b8'
                        },
                        grid: {
                            color: 'rgba(45, 48, 81, 0.5)'
                        }
                    },
                    'y-rate': {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {
                            display: true,
                            text: 'Rate (msg/s)',
                            color: '#b0b3b8'
                        },
                        ticks: {
                            color: '#b0b3b8'
                        },
                        grid: {
                            drawOnChartArea: false
                        }
                    }
                }
            }
        });
    }

    updateQueueChart(labels, messagesData, rateRanges) {
        if (this.queueChart) {
            this.queueChart.data.labels = labels;

            // Messages dataset
            this.queueChart.data.datasets[0].data = messagesData;

            // Prepare rate range and current value data
            const publishRangeData = [];
            const publishRangePoints = [];
            const publishCurrentData = [];
            const ackRangeData = [];
            const ackRangePoints = [];
            const ackCurrentData = [];

            rateRanges.forEach((range, index) => {
                // Publish range data for custom plugin
                publishRangeData.push([range.publish.min, range.publish.max]);
                // Hidden scatter point at center of range for positioning
                publishRangePoints.push({
                    x: index,
                    y: (range.publish.min + range.publish.max) / 2
                });

                // Publish current value as scatter point with slight offset left
                publishCurrentData.push({
                    x: index - 0.15,
                    y: range.publish.current
                });

                // Ack range data for custom plugin
                ackRangeData.push([range.ack.min, range.ack.max]);
                // Hidden scatter point at center of range for positioning
                ackRangePoints.push({
                    x: index,
                    y: (range.ack.min + range.ack.max) / 2
                });

                // Ack current value as scatter point with slight offset right
                ackCurrentData.push({
                    x: index + 0.15,
                    y: range.ack.current
                });
            });

            // Update datasets
            this.queueChart.data.datasets[1].data = publishRangeData;
            this.queueChart.data.datasets[2].data = publishCurrentData;
            this.queueChart.data.datasets[3].data = ackRangeData;
            this.queueChart.data.datasets[4].data = ackCurrentData;

            this.queueChart.update('none'); // 'none' mode for smoother updates
        }
    }

    addLogEntry(message, type = 'info') {
        const timestamp = new Date().toLocaleTimeString();
        this.activityLog.unshift({ timestamp, message, type });

        // Keep only the most recent entries
        if (this.activityLog.length > this.maxLogEntries) {
            this.activityLog.pop();
        }

        this.renderActivityLog();
    }

    renderActivityLog() {
        const container = document.getElementById('activityLog');
        container.innerHTML = this.activityLog.map(entry => `
            <div class="log-entry">
                <span class="log-timestamp">${entry.timestamp}</span>
                ${entry.message}
            </div>
        `).join('');
    }

    updateLastUpdated(timestamp) {
        const element = document.getElementById('lastUpdated');
        element.textContent = this.formatTime(timestamp);
    }

    formatTime(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleString();
    }

}

// Initialize dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new Dashboard();
});
