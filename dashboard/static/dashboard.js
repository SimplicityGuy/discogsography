// Dashboard JavaScript
class Dashboard {
    constructor() {
        this.ws = null;
        this.reconnectInterval = null;
        this.activityLog = [];
        this.maxLogEntries = 50;
        // SVG circle circumference: 2 * PI * r(28) ≈ 176
        this.CIRCUMFERENCE = 176;

        this.gaugeStats = {};
        this.currentMaps = null;

        this.initializeWebSocket();
        this.fetchInitialData();

        const dlqToggle = document.getElementById('dlq-toggle');
        if (dlqToggle) {
            dlqToggle.addEventListener('change', () => this._onDlqToggle());
        }
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

        // Build per-service maps for both regular and dead-letter queues.
        // Queue naming convention: "discogsography-{service}-{type}" and
        // "discogsography-{service}-{type}.dlq" for dead-letter queues.
        // Separate maps prevent DLQ entries from overwriting regular data.
        const graphinatorMap    = {};
        const tableInatorMap    = {};
        const graphinatorDlqMap = {};
        const tableInatorDlqMap = {};

        queues.forEach(queue => {
            const name  = queue.name.toLowerCase();
            const isDlq = name.endsWith('.dlq');

            for (const type of TYPES) {
                if (!name.includes(type)) continue;
                if (name.includes('graphinator')) {
                    if (isDlq) graphinatorDlqMap[type] = queue;
                    else       graphinatorMap[type]    = queue;
                } else if (name.includes('tableinator')) {
                    if (isDlq) tableInatorDlqMap[type] = queue;
                    else       tableInatorMap[type]    = queue;
                }
                break;
            }
        });

        this.currentMaps = { graphinatorMap, tableInatorMap, graphinatorDlqMap, tableInatorDlqMap };

        const isDlq         = document.getElementById('dlq-toggle')?.checked ?? false;
        const activeGraphMap = isDlq ? graphinatorDlqMap : graphinatorMap;
        const activeTableMap = isDlq ? tableInatorDlqMap : tableInatorMap;

        // Extractor card – queue state based on publish rate (always uses regular queues).
        TYPES.forEach(type => {
            const el = document.getElementById(`extractor-${type}-state`);
            if (!el) return;
            const q = graphinatorMap[type] || tableInatorMap[type];
            if (q) {
                const processing = q.message_rate > 0;
                el.textContent = processing ? 'Processing' : 'Idle';
                el.className = processing ? 'text-blue-400' : 'text-emerald-400';
            } else {
                el.textContent = '—';
                el.className = 'text-zinc-500';
            }
        });

        // Graphinator card – total messages in active queue set.
        TYPES.forEach(type => {
            const el = document.getElementById(`graphinator-${type}-count`);
            if (!el) return;
            const q = activeGraphMap[type];
            el.textContent = q ? q.messages.toLocaleString() : '—';
        });

        // Tableinator card – messages in active queue set.
        TYPES.forEach(type => {
            const el = document.getElementById(`tableinator-${type}-count`);
            if (!el) return;
            const q = activeTableMap[type];
            el.textContent = q ? q.messages_ready.toLocaleString() : '—';
        });

        this._updateBarChart(activeGraphMap, activeTableMap, TYPES, isDlq);
        this._updateRateCircles(graphinatorMap, tableInatorMap, TYPES);

        // Log high message counts (regular queues only)
        queues.forEach(queue => {
            if (!queue.name.toLowerCase().endsWith('.dlq') && queue.messages > 1000) {
                this.addLogEntry(
                    `High message count in ${queue.name}: ${queue.messages.toLocaleString()}`,
                    'warning'
                );
            }
        });
    }

    _onDlqToggle() {
        if (!this.currentMaps) return;
        const TYPES = ['masters', 'releases', 'artists', 'labels'];
        const isDlq = document.getElementById('dlq-toggle')?.checked ?? false;
        const { graphinatorMap, tableInatorMap, graphinatorDlqMap, tableInatorDlqMap } = this.currentMaps;
        const activeGraphMap = isDlq ? graphinatorDlqMap : graphinatorMap;
        const activeTableMap = isDlq ? tableInatorDlqMap : tableInatorMap;

        TYPES.forEach(type => {
            const gEl = document.getElementById(`graphinator-${type}-count`);
            if (gEl) {
                const q = activeGraphMap[type];
                gEl.textContent = q ? q.messages.toLocaleString() : '—';
            }
            const tEl = document.getElementById(`tableinator-${type}-count`);
            if (tEl) {
                const q = activeTableMap[type];
                tEl.textContent = q ? q.messages_ready.toLocaleString() : '—';
            }
        });

        this._updateBarChart(activeGraphMap, activeTableMap, TYPES, isDlq);
    }

    // ─── Bar chart (CSS height bars) ─────────────────────────────────────────

    _updateBarChart(graphinatorMap, tableInatorMap, types, isDlq = false) {
        const graphLegend = document.getElementById('chart-legend-graphinator');
        const tableLegend = document.getElementById('chart-legend-tableinator');
        if (graphLegend) graphLegend.textContent = isDlq ? 'Graphinator DLQ' : 'Graphinator';
        if (tableLegend) tableLegend.textContent = isDlq ? 'Tableinator DLQ' : 'Tableinator';

        const allGraphinator = types.map(t => graphinatorMap[t]?.messages || 0);
        const allTableinator = types.map(t => tableInatorMap[t]?.messages || 0);
        const maxCount = Math.max(...allGraphinator, ...allTableinator, 1);

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

        // Update bar heights: purple = graphinator messages, blue = tableinator messages
        types.forEach(type => {
            const gq = graphinatorMap[type];
            const tq = tableInatorMap[type];
            const msgBar   = document.getElementById(`bar-${type}-messages`);
            const readyBar = document.getElementById(`bar-${type}-ready`);
            if (msgBar) {
                const count = gq?.messages || 0;
                const pct = Math.max((count / maxCount) * 100, count > 0 ? 1 : 0);
                msgBar.style.height = `${pct}%`;
            }
            if (readyBar) {
                const count = tq?.messages || 0;
                const pct = Math.max((count / maxCount) * 100, count > 0 ? 1 : 0);
                readyBar.style.height = `${pct}%`;
            }
        });
    }

    // ─── Circular rate gauges ─────────────────────────────────────────────────

    _updateRateCircles(graphinatorMap, tableInatorMap, types) {
        const C = this.CIRCUMFERENCE;

        const updateGauge = (circleId, textId, rate) => {
            const circle = document.getElementById(circleId);
            const text   = document.getElementById(textId);
            if (!circle || !text) return;

            // Track per-gauge min (non-zero) and max
            const s = this.gaugeStats[circleId] ??= { min: Infinity, max: 0 };
            if (rate > 0) s.min = Math.min(s.min, rate);
            s.max = Math.max(s.max, rate);

            // Fill relative to this gauge's own observed max
            const fill = s.max > 0 ? rate / s.max : 0;
            circle.style.strokeDashoffset = fill > 0 ? C - fill * C : C;
            text.textContent = this._formatRate(rate);
            text.className = rate > 0 ? '' : 'text-zinc-600';

            // Show min–max below the gauge label
            const container = text.closest('.flex.flex-col');
            if (container) {
                let statsEl = container.querySelector('.gauge-stats');
                if (!statsEl) {
                    statsEl = document.createElement('span');
                    statsEl.className = 'gauge-stats text-[8px] text-zinc-600 font-mono';
                    container.appendChild(statsEl);
                }
                const minStr = s.min === Infinity ? '—' : this._formatRate(s.min);
                statsEl.textContent = `${minStr}–${this._formatRate(s.max)}`;
            }
        };

        types.forEach(type => {
            const gq = graphinatorMap[type];
            const tq = tableInatorMap[type];
            updateGauge(`rate-circle-graphinator-${type}-publish`, `rate-text-graphinator-${type}-publish`, gq?.message_rate || 0);
            updateGauge(`rate-circle-tableinator-${type}-publish`, `rate-text-tableinator-${type}-publish`, tq?.message_rate || 0);
            updateGauge(`rate-circle-graphinator-${type}-ack`,     `rate-text-graphinator-${type}-ack`,     gq?.ack_rate     || 0);
            updateGauge(`rate-circle-tableinator-${type}-ack`,     `rate-text-tableinator-${type}-ack`,     tq?.ack_rate     || 0);
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
                    badge.textContent = db.status === 'healthy' ? 'Healthy' : 'Unavailable';
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

        container.replaceChildren(
            ...this.activityLog.map(e => {
                const row = document.createElement('div');
                row.className = 'flex items-start space-x-4 log-entry';

                const ts = document.createElement('span');
                ts.className = 'text-zinc-600 shrink-0';
                ts.textContent = e.timestamp;

                const lv = document.createElement('span');
                lv.className = `${levelCls[e.type] || 'text-emerald-500'} font-bold shrink-0`;
                lv.textContent = levelLbl[e.type] || '[INFO]';

                const msg = document.createElement('span');
                msg.className = 'text-zinc-300';
                msg.textContent = e.message;

                row.append(ts, lv, msg);
                return row;
            })
        );
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
