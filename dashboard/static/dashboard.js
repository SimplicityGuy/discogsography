// Dashboard JavaScript
class Dashboard {
    constructor() {
        this.ws = null;
        this.reconnectInterval = null;
        this.activityLog = [];
        this.maxLogEntries = 50;
        // SVG circle circumference: 2 * PI * r(28) ≈ 176
        this.CIRCUMFERENCE = 176;

        this.initializeWebSocket();
        this.fetchInitialData();
    }

    // ─── WebSocket ────────────────────────────────────────────────────────────

    initializeWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.updateConnectionStatus('connected');
            this.addLogEntry('Connected to dashboard', 'info');
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

        this.ws.onerror = () => {
            this.updateConnectionStatus('disconnected');
        };

        this.ws.onclose = () => {
            this.updateConnectionStatus('disconnected');
            this.addLogEntry('Disconnected from dashboard', 'warning');
            this.reconnect();
        };
    }

    reconnect() {
        if (!this.reconnectInterval) {
            this.reconnectInterval = setInterval(() => {
                this.initializeWebSocket();
            }, 5000);
        }
    }

    // ─── Status indicators ────────────────────────────────────────────────────

    updateConnectionStatus(status) {
        const indicator = document.querySelector('.status-indicator');
        const text = document.querySelector('.status-text');

        if (status === 'connected') {
            // NOTE: 'connected' class is kept for Playwright test detection
            if (indicator) indicator.className = 'status-indicator connected w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
            if (text) {
                text.textContent = 'Connected';
                text.className = 'status-text text-[10px] text-emerald-400 font-bold uppercase tracking-widest';
            }
        } else {
            // NOTE: 'disconnected' class is kept for Playwright test detection
            if (indicator) indicator.className = 'status-indicator disconnected w-2 h-2 rounded-full bg-red-500';
            if (text) {
                text.textContent = 'Disconnected';
                text.className = 'status-text text-[10px] text-red-400 font-bold uppercase tracking-widest';
            }
        }
    }

    updateOverallStatus(services) {
        const dot = document.getElementById('operational-status-dot');
        const text = document.getElementById('operational-status-text');
        if (!dot || !text) return;

        const allHealthy = services.length > 0 && services.every(s => s.status === 'healthy');
        const anyUnhealthy = services.some(s => s.status === 'unhealthy');

        if (allHealthy) {
            dot.className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
            text.className = 'text-[10px] text-emerald-500 font-bold uppercase tracking-widest';
            text.textContent = 'Operational';
        } else if (anyUnhealthy) {
            dot.className = 'w-2 h-2 rounded-full bg-red-500';
            text.className = 'text-[10px] text-red-500 font-bold uppercase tracking-widest';
            text.textContent = 'Degraded';
        } else {
            dot.className = 'w-2 h-2 rounded-full bg-yellow-500 animate-pulse';
            text.className = 'text-[10px] text-yellow-500 font-bold uppercase tracking-widest';
            text.textContent = 'Unknown';
        }
    }

    // ─── Initial data fetch ───────────────────────────────────────────────────

    async fetchInitialData() {
        try {
            const response = await fetch('/api/metrics');
            if (response.ok) {
                const data = await response.json();
                this.updateDashboard(data);
            }
        } catch (error) {
            this.addLogEntry('Failed to fetch initial data', 'error');
        }
    }

    // ─── Main update dispatcher ───────────────────────────────────────────────

    updateDashboard(data) {
        this.updateServices(data.services);
        this.updateQueues(data.queues);
        this.updateDatabases(data.databases);
        this.updateLastUpdated(data.timestamp);
        this.updateOverallStatus(data.services);
    }

    // ─── Service cards ────────────────────────────────────────────────────────

    _serviceBadgeClasses(status) {
        switch (status.toLowerCase()) {
            case 'healthy':
                return 'text-[10px] px-2 py-0.5 rounded uppercase font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
            case 'unhealthy':
                return 'text-[10px] px-2 py-0.5 rounded uppercase font-bold bg-red-500/10 text-red-400 border border-red-500/20';
            case 'extracting':
            case 'active':
                return 'text-[10px] px-2 py-0.5 rounded uppercase font-bold bg-purple-500/10 text-purple-400 border border-purple-500/20';
            default:
                return 'text-[10px] px-2 py-0.5 rounded uppercase font-bold bg-yellow-500/10 text-yellow-400 border border-yellow-500/20';
        }
    }

    _statusLabel(status) {
        switch (status.toLowerCase()) {
            case 'healthy':    return 'Healthy';
            case 'unhealthy':  return 'Unhealthy';
            case 'extracting': return 'Active';
            case 'unknown':    return 'Unknown';
            default:           return status;
        }
    }

    updateServices(services) {
        services.forEach(service => {
            const badge = document.getElementById(`${service.name}-status-badge`);
            if (badge) {
                badge.className = this._serviceBadgeClasses(service.status);
                badge.textContent = this._statusLabel(service.status);
            }
        });
    }

    // ─── Queue metrics ────────────────────────────────────────────────────────

    updateQueues(queues) {
        const TYPES = ['masters', 'releases', 'artists', 'labels'];

        // Map queue type → queue object. Queue names like "discogsography-masters".
        const queueMap = {};
        queues.forEach(queue => {
            const name = queue.name.toLowerCase();
            for (const type of TYPES) {
                if (name.includes(type)) {
                    queueMap[type] = queue;
                    break;
                }
            }
        });

        // Extractor card – queue state based on publish rate
        TYPES.forEach(type => {
            const el = document.getElementById(`extractor-${type}-state`);
            if (!el) return;
            const q = queueMap[type];
            if (q) {
                const processing = q.message_rate > 0;
                el.textContent = processing ? 'Processing' : 'Idle';
                el.className = processing ? 'text-blue-400' : 'text-emerald-400';
            } else {
                el.textContent = '—';
                el.className = 'text-zinc-500';
            }
        });

        // Graphinator card – total messages in queue
        TYPES.forEach(type => {
            const el = document.getElementById(`graphinator-${type}-count`);
            if (!el) return;
            const q = queueMap[type];
            el.textContent = q ? q.messages.toLocaleString() : '—';
        });

        // Tableinator card – messages ready to process
        TYPES.forEach(type => {
            const el = document.getElementById(`tableinator-${type}-count`);
            if (!el) return;
            const q = queueMap[type];
            el.textContent = q ? q.messages_ready.toLocaleString() : '—';
        });

        this._updateBarChart(queueMap, TYPES);
        this._updateRateCircles(queueMap, TYPES);

        // Log high message counts
        queues.forEach(queue => {
            if (queue.messages > 1000) {
                this.addLogEntry(
                    `High message count in ${queue.name}: ${queue.messages.toLocaleString()}`,
                    'warning'
                );
            }
        });
    }

    // ─── Bar chart (SVG-less, CSS height bars) ────────────────────────────────

    _updateBarChart(queueMap, types) {
        const allMessages = types.map(t => queueMap[t]?.messages || 0);
        const allReady    = types.map(t => queueMap[t]?.messages_ready || 0);
        const maxCount = Math.max(...allMessages, ...allReady, 1);

        // Update Y-axis labels
        const fmt = this._formatCount.bind(this);
        const y4 = document.getElementById('bar-yaxis-4');
        const y3 = document.getElementById('bar-yaxis-3');
        const y2 = document.getElementById('bar-yaxis-2');
        const y1 = document.getElementById('bar-yaxis-1');
        if (y4) y4.textContent = fmt(maxCount);
        if (y3) y3.textContent = fmt(maxCount * 0.75);
        if (y2) y2.textContent = fmt(maxCount * 0.5);
        if (y1) y1.textContent = fmt(maxCount * 0.25);

        // Update bar heights
        types.forEach(type => {
            const q = queueMap[type];
            const msgBar   = document.getElementById(`bar-${type}-messages`);
            const readyBar = document.getElementById(`bar-${type}-ready`);
            if (msgBar) {
                const pct = q ? Math.max((q.messages / maxCount) * 100, q.messages > 0 ? 1 : 0) : 0;
                msgBar.style.height = `${pct}%`;
            }
            if (readyBar) {
                const pct = q ? Math.max((q.messages_ready / maxCount) * 100, q.messages_ready > 0 ? 1 : 0) : 0;
                readyBar.style.height = `${pct}%`;
            }
        });
    }

    // ─── Circular rate gauges ─────────────────────────────────────────────────

    _updateRateCircles(queueMap, types) {
        const allPublish = types.map(t => queueMap[t]?.message_rate || 0);
        const allAck     = types.map(t => queueMap[t]?.ack_rate     || 0);
        const maxRate = Math.max(...allPublish, ...allAck, 1);

        const C = this.CIRCUMFERENCE;

        types.forEach(type => {
            const q = queueMap[type];

            // Publish gauge
            const pubCircle = document.getElementById(`rate-circle-${type}-publish`);
            const pubText   = document.getElementById(`rate-text-${type}-publish`);
            if (pubCircle && pubText) {
                const rate = q?.message_rate || 0;
                pubCircle.style.strokeDashoffset = rate > 0 ? C - (rate / maxRate) * C : C;
                pubText.textContent = this._formatRate(rate);
                pubText.className = rate > 0 ? '' : 'text-zinc-600';
            }

            // Ack gauge
            const ackCircle = document.getElementById(`rate-circle-${type}-ack`);
            const ackText   = document.getElementById(`rate-text-${type}-ack`);
            if (ackCircle && ackText) {
                const rate = q?.ack_rate || 0;
                ackCircle.style.strokeDashoffset = rate > 0 ? C - (rate / maxRate) * C : C;
                ackText.textContent = this._formatRate(rate);
                ackText.className = rate > 0 ? '' : 'text-zinc-600';
            }
        });
    }

    // ─── Database cards ───────────────────────────────────────────────────────

    updateDatabases(databases) {
        databases.forEach(db => {
            const key = db.name.toLowerCase();

            if (key === 'neo4j') {
                const badge = document.getElementById('neo4j-status-badge');
                const nodesEl = document.getElementById('neo4j-nodes');
                const relsEl  = document.getElementById('neo4j-relationships');

                if (badge) {
                    badge.textContent = db.status === 'healthy' ? 'Primary' : 'Unavailable';
                    badge.className = `text-[10px] font-bold uppercase ${db.status === 'healthy' ? 'text-emerald-400' : 'text-red-400'}`;
                }

                if (nodesEl && relsEl) {
                    if (db.size && db.status === 'healthy') {
                        // Backend formats as "X nodes, Y relationships"
                        const m = db.size.match(/^([\d,]+)\s+nodes?,\s+([\d,]+)\s+relationships?/i);
                        if (m) {
                            nodesEl.textContent = m[1];
                            relsEl.textContent  = m[2];
                        } else {
                            nodesEl.textContent = db.size;
                            relsEl.textContent  = '—';
                        }
                    } else {
                        nodesEl.textContent = db.error ? 'Error' : '—';
                        relsEl.textContent  = '—';
                    }
                }

            } else if (key === 'postgresql') {
                const badge  = document.getElementById('postgresql-status-badge');
                const connEl = document.getElementById('postgresql-connections');
                const sizeEl = document.getElementById('postgresql-size');

                if (badge) {
                    badge.textContent = db.status === 'healthy' ? 'Healthy' : 'Unavailable';
                    badge.className = `text-[10px] font-bold uppercase ${db.status === 'healthy' ? 'text-emerald-400' : 'text-red-400'}`;
                }
                if (connEl) connEl.textContent = db.connection_count.toString();
                if (sizeEl) sizeEl.textContent = db.size || '—';
            }
        });
    }

    // ─── Activity log ─────────────────────────────────────────────────────────

    addLogEntry(message, type = 'info') {
        const ts = new Date().toLocaleTimeString('en-US', {
            hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
        this.activityLog.unshift({ timestamp: ts, message, type });
        if (this.activityLog.length > this.maxLogEntries) this.activityLog.pop();
        this.renderActivityLog();
    }

    renderActivityLog() {
        const container = document.getElementById('activityLog');
        if (!container) return;

        const levelCls = { info: 'text-emerald-500', warning: 'text-orange-500', error: 'text-red-500' };
        const levelLbl = { info: '[INFO]',            warning: '[WARN]',          error: '[ERR]'        };

        container.innerHTML = this.activityLog.map(e => `
            <div class="flex items-start space-x-4 log-entry">
                <span class="text-zinc-600 shrink-0">${e.timestamp}</span>
                <span class="${levelCls[e.type] || 'text-emerald-500'} font-bold shrink-0">${levelLbl[e.type] || '[INFO]'}</span>
                <span class="text-zinc-300">${e.message}</span>
            </div>
        `).join('');
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────

    updateLastUpdated(timestamp) {
        const el = document.getElementById('lastUpdated');
        if (el) el.textContent = new Date(timestamp).toLocaleString();
    }

    // Kept for backward-compatibility with any external callers
    formatTime(timestamp) {
        return new Date(timestamp).toLocaleString();
    }

    _formatRate(rate) {
        if (rate >= 1000) return `${(rate / 1000).toFixed(1)}k`;
        return rate.toFixed(1);
    }

    _formatCount(count) {
        if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
        if (count >= 1_000)     return `${(count / 1_000).toFixed(0)}K`;
        return Math.round(count).toString();
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new Dashboard();
});
