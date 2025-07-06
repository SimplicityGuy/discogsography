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

    updateQueues(queues) {
        const container = document.getElementById('queuesGrid');
        container.innerHTML = '';

        // Update chart data
        const labels = [];
        const messagesData = [];
        const rateData = [];

        queues.forEach(queue => {
            const card = this.createQueueCard(queue);
            container.appendChild(card);

            // Collect data for chart
            const shortName = queue.name.replace('discogsography-', '');
            labels.push(shortName);
            messagesData.push(queue.messages);
            rateData.push(queue.message_rate);
        });

        // Update chart
        this.updateQueueChart(labels, messagesData, rateData);

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
        this.queueChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Messages',
                    data: [],
                    backgroundColor: 'rgba(24, 119, 242, 0.6)',
                    borderColor: 'rgba(24, 119, 242, 1)',
                    borderWidth: 1,
                    yAxisID: 'y-messages'
                }, {
                    label: 'Message Rate (msg/s)',
                    data: [],
                    type: 'line',
                    backgroundColor: 'rgba(66, 184, 131, 0.6)',
                    borderColor: 'rgba(66, 184, 131, 1)',
                    borderWidth: 2,
                    yAxisID: 'y-rate',
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        labels: {
                            color: '#e4e6eb'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Queue Statistics',
                        color: '#e4e6eb'
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

    updateQueueChart(labels, messagesData, rateData) {
        if (this.queueChart) {
            this.queueChart.data.labels = labels;
            this.queueChart.data.datasets[0].data = messagesData;
            this.queueChart.data.datasets[1].data = rateData;
            this.queueChart.update();
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
