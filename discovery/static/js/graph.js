// Music Knowledge Graph Explorer Module

class GraphModule {
    constructor() {
        this.network = null;
        this.nodes = new vis.DataSet([]);
        this.edges = new vis.DataSet([]);
        this.selectedNode = null;
        this.currentQuery = null;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupNetworkVisualization();
        this.updateQueryControls();
    }

    setupEventListeners() {
        const exploreBtn = document.getElementById('exploreGraph');
        const clearBtn = document.getElementById('clearGraph');
        const queryType = document.getElementById('queryType');

        exploreBtn.addEventListener('click', () => {
            this.exploreGraph();
        });

        clearBtn.addEventListener('click', () => {
            this.clearGraph();
        });

        queryType.addEventListener('change', () => {
            this.updateQueryControls();
        });

        // Handle enter key in search input
        document.getElementById('graphQuery').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.exploreGraph();
            }
        });

        document.getElementById('targetNode').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.exploreGraph();
            }
        });
    }

    updateQueryControls() {
        const queryType = document.getElementById('queryType').value;
        const pathControls = document.getElementById('pathControls');
        const graphQuery = document.getElementById('graphQuery');

        // Show/hide path controls
        pathControls.style.display = queryType === 'path' ? 'block' : 'none';

        // Update placeholder text
        const placeholders = {
            'search': 'Search for artists, releases, labels...',
            'expand': 'Enter node ID to expand around',
            'path': 'Enter source node ID',
            'neighborhood': 'Enter node ID to show neighborhood',
            'semantic': 'Enter semantic search query'
        };

        graphQuery.placeholder = placeholders[queryType] || 'Enter search query';
    }

    setupNetworkVisualization() {
        const container = document.getElementById('graphVisualization');

        const options = {
            nodes: {
                shape: 'dot',
                size: 16,
                font: {
                    size: 12,
                    color: '#ffffff',
                    background: 'rgba(0,0,0,0.5)'
                },
                borderWidth: 2,
                shadow: true
            },
            edges: {
                width: 2,
                color: {
                    color: '#848484',
                    highlight: '#667eea',
                    hover: '#667eea'
                },
                arrows: {
                    to: { enabled: false }
                },
                font: {
                    color: '#ffffff',
                    size: 10,
                    background: 'rgba(0,0,0,0.5)'
                },
                smooth: {
                    type: 'continuous'
                }
            },
            physics: {
                stabilization: false,
                forceAtlas2Based: {
                    gravitationalConstant: -26,
                    centralGravity: 0.005,
                    springLength: 230,
                    springConstant: 0.18
                },
                maxVelocity: 146,
                solver: 'forceAtlas2Based',
                timestep: 0.35,
                adaptiveTimestep: true
            },
            interaction: {
                hover: true,
                hoverConnectedEdges: true,
                selectConnectedEdges: false
            },
            layout: {
                improvedLayout: true
            }
        };

        const data = {
            nodes: this.nodes,
            edges: this.edges
        };

        this.network = new vis.Network(container, data, options);
        this.setupNetworkEvents();
    }

    setupNetworkEvents() {
        // Node selection
        this.network.on('selectNode', (params) => {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                this.selectedNode = nodeId;
                this.displayNodeInfo(nodeId);
            }
        });

        // Node double-click to expand
        this.network.on('doubleClick', (params) => {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                this.expandNode(nodeId);
            }
        });

        // Hover effects
        this.network.on('hoverNode', (params) => {
            const nodeId = params.node;
            this.highlightNode(nodeId);
        });

        this.network.on('blurNode', () => {
            this.unhighlightAll();
        });

        // Edge selection
        this.network.on('selectEdge', (params) => {
            if (params.edges.length > 0) {
                const edgeId = params.edges[0];
                this.displayEdgeInfo(edgeId);
            }
        });
    }

    async exploreGraph() {
        const queryType = document.getElementById('queryType').value;
        const searchQuery = document.getElementById('graphQuery').value.trim();
        const targetNode = document.getElementById('targetNode').value.trim();
        const maxDepth = parseInt(document.getElementById('maxDepth').value);

        if (!searchQuery) {
            window.discoveryApp.showToast('Please enter a search query', 'error');
            return;
        }

        const query = {
            query_type: queryType,
            max_depth: maxDepth,
            limit: 50
        };

        // Add parameters based on query type
        switch (queryType) {
            case 'search':
            case 'semantic':
                query.search_term = searchQuery;
                break;
            case 'expand':
            case 'neighborhood':
                query.node_id = searchQuery;
                break;
            case 'path':
                query.source_node = searchQuery;
                query.target_node = targetNode;
                if (!targetNode) {
                    window.discoveryApp.showToast('Please enter both source and target node IDs', 'error');
                    return;
                }
                break;
        }

        try {
            const response = await window.discoveryApp.makeAPIRequest('graph/explore', query, 'POST');
            this.currentQuery = response;
            this.displayGraph(response);

            if (response.path) {
                this.displayPathResult(response.path);
            }

            window.discoveryApp.showToast(
                `Graph exploration completed (${response.graph.nodes.length} nodes)`,
                'success'
            );
        } catch (error) {
            console.error('Error exploring graph:', error);
            this.displayError('Failed to explore graph. Please try again.');
        }
    }

    displayGraph(response) {
        const graphData = response.graph;

        if (!graphData.nodes || graphData.nodes.length === 0) {
            this.displayEmptyState();
            return;
        }

        // Clear existing data
        this.nodes.clear();
        this.edges.clear();

        // Add nodes
        const visNodes = graphData.nodes.map(node => ({
            id: node.id,
            label: node.name,
            title: this.createNodeTooltip(node),
            color: {
                background: node.color,
                border: this.darkenColor(node.color, 0.3),
                highlight: {
                    background: node.color,
                    border: this.darkenColor(node.color, 0.5)
                }
            },
            size: node.size,
            font: {
                size: Math.max(10, node.size / 2),
                color: '#ffffff'
            },
            nodeType: node.label,
            properties: node.properties
        }));

        // Add edges
        const visEdges = graphData.edges.map(edge => ({
            id: edge.id,
            from: edge.source,
            to: edge.target,
            label: edge.label,
            title: this.createEdgeTooltip(edge),
            width: Math.max(1, edge.weight * 2),
            properties: edge.properties
        }));

        this.nodes.add(visNodes);
        this.edges.add(visEdges);

        // Fit the graph to view
        this.network.fit({
            animation: {
                duration: 1000,
                easingFunction: 'easeInOutQuad'
            }
        });

        // Update info panel
        this.updateGraphStats(graphData);
    }

    expandNode(nodeId) {
        if (!nodeId) return;

        // Set the expand query and trigger exploration
        document.getElementById('queryType').value = 'expand';
        document.getElementById('graphQuery').value = nodeId;
        this.updateQueryControls();
        this.exploreGraph();
    }

    displayNodeInfo(nodeId) {
        const node = this.nodes.get(nodeId);
        if (!node) return;

        const infoContainer = document.getElementById('nodeInfo');

        const html = `
            <div class="node-details">
                <h4><i class="fas fa-circle" style="color: ${node.color.background};"></i> ${node.nodeType}</h4>
                <h3>${this.sanitize(node.label)}</h3>

                <div class="node-actions">
                    <button class="btn btn-secondary btn-sm" onclick="window.graphModule.expandNode('${nodeId}')">
                        <i class="fas fa-expand-arrows-alt"></i> Expand
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="window.graphModule.focusNode('${nodeId}')">
                        <i class="fas fa-crosshairs"></i> Focus
                    </button>
                </div>

                ${this.formatNodeProperties(node.properties)}
            </div>
        `;

        infoContainer.innerHTML = html;
    }

    displayEdgeInfo(edgeId) {
        const edge = this.edges.get(edgeId);
        if (!edge) return;

        const infoContainer = document.getElementById('nodeInfo');

        const html = `
            <div class="edge-details">
                <h4><i class="fas fa-arrow-right"></i> Relationship</h4>
                <h3>${this.sanitize(edge.label)}</h3>

                <div class="relationship-info">
                    <p><strong>Weight:</strong> ${edge.width / 2}</p>
                    ${this.formatEdgeProperties(edge.properties)}
                </div>
            </div>
        `;

        infoContainer.innerHTML = html;
    }

    displayPathResult(pathResult) {
        const container = document.getElementById('pathResult');

        const html = `
            <h3><i class="fas fa-route"></i> Path Found</h3>
            <div class="path-info">
                <p><strong>Path Length:</strong> ${pathResult.path_length} degrees of separation</p>
                <p><strong>Total Paths:</strong> ${pathResult.total_paths}</p>
                <p><strong>Explanation:</strong> ${this.sanitize(pathResult.explanation)}</p>
            </div>
            <div class="path-nodes">
                <h4>Path:</h4>
                <div class="path-chain">
                    ${pathResult.path.map((nodeId, index) => {
                        const node = this.nodes.get(nodeId);
                        const nodeName = node ? node.label : nodeId;
                        const arrow = index < pathResult.path.length - 1 ? '<i class="fas fa-arrow-right"></i>' : '';
                        return `<span class="path-node" onclick="window.graphModule.focusNode('${nodeId}')">${this.sanitize(nodeName)}</span>${arrow}`;
                    }).join(' ')}
                </div>
            </div>
        `;

        container.innerHTML = html;
        container.style.display = 'block';
    }

    focusNode(nodeId) {
        if (!this.network || !nodeId) return;

        this.network.focus(nodeId, {
            scale: 1.5,
            animation: {
                duration: 1000,
                easingFunction: 'easeInOutQuad'
            }
        });

        this.network.selectNodes([nodeId]);
    }

    highlightNode(nodeId) {
        const connectedNodes = this.network.getConnectedNodes(nodeId);
        const connectedEdges = this.network.getConnectedEdges(nodeId);

        // Update visual styles for highlighting
        this.network.setSelection({
            nodes: [nodeId],
            edges: connectedEdges
        });
    }

    unhighlightAll() {
        this.network.setSelection({ nodes: [], edges: [] });
    }

    clearGraph() {
        this.nodes.clear();
        this.edges.clear();
        document.getElementById('nodeInfo').innerHTML = 'Click on a node to see details';
        document.getElementById('pathResult').style.display = 'none';
        this.selectedNode = null;
        this.currentQuery = null;

        window.discoveryApp.showToast('Graph cleared', 'success');
    }

    updateGraphStats(graphData) {
        const stats = graphData.metadata || {};
        const nodeTypes = {};

        // Count node types
        graphData.nodes.forEach(node => {
            nodeTypes[node.label] = (nodeTypes[node.label] || 0) + 1;
        });

        const statsHtml = `
            <div class="graph-stats">
                <h4>Graph Statistics</h4>
                <div class="stats-grid">
                    <div class="stat-item">
                        <span class="stat-label">Total Nodes:</span>
                        <span class="stat-value">${graphData.nodes.length}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Edges:</span>
                        <span class="stat-value">${graphData.edges.length}</span>
                    </div>
                    ${Object.entries(nodeTypes).map(([type, count]) => `
                        <div class="stat-item">
                            <span class="stat-label">${type}s:</span>
                            <span class="stat-value">${count}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        // Append stats to info panel
        const infoPanel = document.getElementById('nodeInfo');
        if (!infoPanel.innerHTML.includes('graph-stats')) {
            infoPanel.innerHTML += statsHtml;
        }
    }

    createNodeTooltip(node) {
        const props = node.properties || {};
        const details = Object.entries(props)
            .slice(0, 3)
            .map(([key, value]) => `${key}: ${value}`)
            .join('<br>');

        return `<strong>${node.label}: ${node.name}</strong><br>${details}`;
    }

    createEdgeTooltip(edge) {
        const props = edge.properties || {};
        const details = Object.entries(props)
            .slice(0, 2)
            .map(([key, value]) => `${key}: ${value}`)
            .join('<br>');

        return `<strong>${edge.label}</strong><br>Weight: ${edge.weight}<br>${details}`;
    }

    formatNodeProperties(properties) {
        if (!properties || Object.keys(properties).length === 0) {
            return '<p><em>No additional properties</em></p>';
        }

        const items = Object.entries(properties)
            .filter(([key]) => !['name', 'title', 'id'].includes(key))
            .map(([key, value]) => {
                const formattedKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                let formattedValue = value;

                if (Array.isArray(value)) {
                    formattedValue = value.join(', ');
                } else if (typeof value === 'object') {
                    formattedValue = JSON.stringify(value);
                }

                return `
                    <div class="property-item">
                        <span class="property-key">${formattedKey}:</span>
                        <span class="property-value">${this.sanitize(String(formattedValue))}</span>
                    </div>
                `;
            }).join('');

        return items ? `<div class="node-properties">${items}</div>` : '';
    }

    formatEdgeProperties(properties) {
        if (!properties || Object.keys(properties).length === 0) {
            return '';
        }

        return this.formatNodeProperties(properties);
    }

    displayEmptyState() {
        const container = document.getElementById('graphVisualization');
        container.innerHTML = `
            <div class="empty-graph-state">
                <div class="empty-icon">
                    <i class="fas fa-project-diagram" style="font-size: 4rem; color: var(--text-muted);"></i>
                </div>
                <h3>No Graph Data Found</h3>
                <p>No nodes or relationships match your query.</p>
                <div class="suggestions">
                    <ul>
                        <li>Check your search terms</li>
                        <li>Try a different query type</li>
                        <li>Increase the search depth</li>
                        <li>Use broader search criteria</li>
                    </ul>
                </div>
            </div>
        `;
    }

    displayError(message) {
        const container = document.getElementById('graphVisualization');
        container.innerHTML = `
            <div class="graph-error-state">
                <div class="error-icon">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: var(--error-color);"></i>
                </div>
                <h3>Graph Exploration Error</h3>
                <p>${this.sanitize(message)}</p>
                <button class="btn btn-primary" onclick="window.graphModule.exploreGraph()">
                    <i class="fas fa-redo"></i> Try Again
                </button>
            </div>
        `;
    }

    darkenColor(color, factor) {
        // Simple color darkening utility
        const hex = color.replace('#', '');
        const r = Math.max(0, parseInt(hex.substr(0, 2), 16) * (1 - factor));
        const g = Math.max(0, parseInt(hex.substr(2, 2), 16) * (1 - factor));
        const b = Math.max(0, parseInt(hex.substr(4, 2), 16) * (1 - factor));

        return `#${Math.round(r).toString(16).padStart(2, '0')}${Math.round(g).toString(16).padStart(2, '0')}${Math.round(b).toString(16).padStart(2, '0')}`;
    }

    sanitize(str) {
        if (!str) return '';
        const temp = document.createElement('div');
        temp.textContent = str;
        return temp.innerHTML;
    }

    // Export graph data
    exportGraph() {
        if (!this.currentQuery) {
            window.discoveryApp.showToast('No graph data to export', 'warning');
            return;
        }

        const data = {
            timestamp: new Date().toISOString(),
            query: this.currentQuery,
            nodes: this.nodes.get(),
            edges: this.edges.get()
        };

        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `music-graph-${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        URL.revokeObjectURL(url);
        window.discoveryApp.showToast('Graph data exported successfully', 'success');
    }
}

// Initialize the module
window.graphModule = new GraphModule();

// Add CSS for graph-specific styling
const graphStyle = document.createElement('style');
graphStyle.textContent = `
    .node-details, .edge-details {
        padding: 15px;
        background: var(--dark-bg);
        border-radius: var(--radius);
        margin-bottom: 15px;
    }

    .node-details h4, .edge-details h4 {
        color: var(--secondary-color);
        margin-bottom: 5px;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .node-details h3, .edge-details h3 {
        color: var(--primary-color);
        margin-bottom: 15px;
    }

    .node-actions {
        margin: 15px 0;
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
    }

    .node-properties, .relationship-info {
        margin-top: 15px;
    }

    .property-item {
        margin: 8px 0;
        padding: 8px;
        background: var(--darker-bg);
        border-radius: 4px;
        border-left: 3px solid var(--primary-color);
    }

    .property-key {
        font-weight: bold;
        color: var(--primary-color);
        display: inline-block;
        min-width: 80px;
    }

    .property-value {
        color: var(--text-light);
        word-break: break-word;
    }

    .graph-stats {
        margin-top: 20px;
        padding: 15px;
        background: var(--darker-bg);
        border-radius: var(--radius);
    }

    .graph-stats h4 {
        color: var(--secondary-color);
        margin-bottom: 15px;
    }

    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 10px;
    }

    .stat-item {
        display: flex;
        justify-content: space-between;
        padding: 8px;
        background: var(--dark-bg);
        border-radius: 4px;
    }

    .stat-label {
        color: var(--text-muted);
        font-size: 0.9rem;
    }

    .stat-value {
        color: var(--primary-color);
        font-weight: bold;
    }

    .path-info {
        margin: 15px 0;
        padding: 15px;
        background: var(--dark-bg);
        border-radius: var(--radius);
    }

    .path-chain {
        margin-top: 10px;
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 10px;
    }

    .path-node {
        background: var(--primary-color);
        color: white;
        padding: 6px 12px;
        border-radius: 15px;
        cursor: pointer;
        transition: all 0.3s ease;
        font-size: 0.9rem;
    }

    .path-node:hover {
        background: var(--secondary-color);
        transform: translateY(-2px);
    }

    .empty-graph-state, .graph-error-state {
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        height: 100%;
        text-align: center;
        color: var(--text-muted);
        padding: 40px;
    }

    .empty-graph-state h3, .graph-error-state h3 {
        margin: 20px 0;
        color: var(--text-light);
    }

    #pathControls {
        transition: all 0.3s ease;
    }

    .vis-network {
        background: var(--darker-bg) !important;
    }
`;
document.head.appendChild(graphStyle);
