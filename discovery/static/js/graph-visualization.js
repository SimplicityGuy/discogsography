// Graph Visualization using D3.js

class GraphVisualization {
    constructor(svgId) {
        this.svgId = svgId;
        this.svg = d3.select(`#${svgId}`);
        this.width = 800;
        this.height = 600;
        this.simulation = null;
        this.nodes = [];
        this.links = [];
        this.transform = d3.zoomIdentity;

        this.nodeTypes = {
            artist: { color: '#1DB954', size: 10 },
            release: { color: '#FF6B6B', size: 8 },
            label: { color: '#6c757d', size: 9 },
            genre: { color: '#ffc107', size: 7 }
        };

        this.onNodeClick = null;
        this.init();
    }

    init() {
        // Get actual dimensions
        const container = this.svg.node().parentElement;
        this.width = container.clientWidth;
        this.height = container.clientHeight;

        // Clear any existing content
        this.svg.selectAll('*').remove();

        // Create container group
        this.container = this.svg.append('g');

        // Add zoom behavior
        this.zoomBehavior = d3.zoom()
            .scaleExtent([0.1, 10])
            .on('zoom', (event) => {
                this.transform = event.transform;
                this.container.attr('transform', event.transform);
            });

        this.svg.call(this.zoomBehavior);

        // Add arrow markers for directed edges
        this.svg.append('defs').selectAll('marker')
            .data(['arrow'])
            .enter().append('marker')
            .attr('id', d => d)
            .attr('viewBox', '0 -5 10 10')
            .attr('refX', 20)
            .attr('refY', 0)
            .attr('markerWidth', 8)
            .attr('markerHeight', 8)
            .attr('orient', 'auto')
            .append('path')
            .attr('d', 'M0,-5L10,0L0,5')
            .attr('fill', '#999');

        // Create force simulation
        this.simulation = d3.forceSimulation()
            .force('link', d3.forceLink().id(d => d.id).distance(60))
            .force('charge', d3.forceManyBody().strength(-300))
            .force('center', d3.forceCenter(this.width / 2, this.height / 2))
            .force('collision', d3.forceCollide().radius(d => this.getNodeSize(d) + 5));

        // Add legend
        this.addLegend();

        // Handle window resize
        window.addEventListener('resize', () => this.handleResize());
    }

    render(data) {
        if (!data || !data.nodes || !data.links) {
            console.error('Invalid graph data');
            return;
        }

        // Update data
        this.nodes = data.nodes;
        this.links = data.links;

        // Clear previous visualization
        this.container.selectAll('.link').remove();
        this.container.selectAll('.node').remove();

        // Create links
        const link = this.container.append('g')
            .attr('class', 'links')
            .selectAll('line')
            .data(this.links)
            .enter().append('line')
            .attr('class', d => `link ${d.type || ''}`)
            .attr('marker-end', d => d.directed ? 'url(#arrow)' : null);

        // Create nodes
        const node = this.container.append('g')
            .attr('class', 'nodes')
            .selectAll('g')
            .data(this.nodes)
            .enter().append('g')
            .attr('class', d => `node ${d.type}`)
            .call(this.drag());

        // Add circles to nodes
        node.append('circle')
            .attr('r', d => this.getNodeSize(d))
            .attr('fill', d => this.getNodeColor(d));

        // Add labels to nodes
        const showLabels = document.getElementById('showLabels')?.checked ?? true;
        if (showLabels) {
            node.append('text')
                .attr('x', 0)
                .attr('y', -15)
                .attr('text-anchor', 'middle')
                .attr('font-size', '12px')
                .attr('font-weight', '500')
                .text(d => d.name || d.label || '')
                .style('pointer-events', 'none');
        }

        // Add tooltips
        node.append('title')
            .text(d => this.getNodeTooltip(d));

        // Handle node clicks
        node.on('click', (event, d) => {
            event.stopPropagation();
            if (this.onNodeClick) {
                this.onNodeClick(d);
            }
            this.highlightNode(d);
        });

        // Handle node hover
        node.on('mouseenter', (event, d) => {
            this.highlightConnections(d);
        }).on('mouseleave', () => {
            this.resetHighlight();
        });

        // Update simulation
        this.simulation.nodes(this.nodes);
        this.simulation.force('link').links(this.links);
        this.simulation.alpha(1).restart();

        // Update positions on tick
        this.simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });
    }

    getNodeSize(node) {
        const baseSize = this.nodeTypes[node.type]?.size || 8;
        // Scale size based on connections if available
        if (node.connections) {
            return baseSize + Math.min(node.connections * 0.5, 10);
        }
        return baseSize;
    }

    getNodeColor(node) {
        return this.nodeTypes[node.type]?.color || '#999';
    }

    getNodeTooltip(node) {
        let tooltip = node.name || node.label || 'Unknown';
        if (node.type) tooltip += `\nType: ${node.type}`;
        if (node.year) tooltip += `\nYear: ${node.year}`;
        if (node.genres?.length > 0) tooltip += `\nGenres: ${node.genres.join(', ')}`;
        return tooltip;
    }

    highlightNode(node) {
        // Reset all nodes
        this.container.selectAll('.node')
            .classed('highlighted', false)
            .style('opacity', 0.3);

        // Highlight selected node
        this.container.selectAll('.node')
            .filter(d => d.id === node.id)
            .classed('highlighted', true)
            .style('opacity', 1);

        // Highlight connected nodes
        const connectedNodeIds = new Set();
        this.links.forEach(link => {
            if (link.source.id === node.id) connectedNodeIds.add(link.target.id);
            if (link.target.id === node.id) connectedNodeIds.add(link.source.id);
        });

        this.container.selectAll('.node')
            .filter(d => connectedNodeIds.has(d.id))
            .style('opacity', 0.8);
    }

    highlightConnections(node) {
        // Dim all elements
        this.container.selectAll('.node').style('opacity', 0.3);
        this.container.selectAll('.link').style('opacity', 0.1);

        // Highlight the hovered node
        this.container.selectAll('.node')
            .filter(d => d.id === node.id)
            .style('opacity', 1);

        // Highlight connected links and nodes
        this.container.selectAll('.link')
            .filter(d => d.source.id === node.id || d.target.id === node.id)
            .style('opacity', 0.8)
            .each(function(d) {
                // Highlight connected nodes
                const connectedId = d.source.id === node.id ? d.target.id : d.source.id;
                d3.selectAll('.node')
                    .filter(n => n.id === connectedId)
                    .style('opacity', 0.8);
            });
    }

    resetHighlight() {
        this.container.selectAll('.node').style('opacity', 1);
        this.container.selectAll('.link').style('opacity', 0.6);
    }

    drag() {
        return d3.drag()
            .on('start', (event, d) => {
                if (!event.active) this.simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            })
            .on('drag', (event, d) => {
                d.fx = event.x;
                d.fy = event.y;
            })
            .on('end', (event, d) => {
                if (!event.active) this.simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            });
    }

    addLegend() {
        const legend = this.svg.append('g')
            .attr('class', 'legend')
            .attr('transform', `translate(20, 20)`);

        const legendItems = Object.entries(this.nodeTypes).map(([type, config]) => ({
            type,
            label: type.charAt(0).toUpperCase() + type.slice(1),
            color: config.color
        }));

        const legendItem = legend.selectAll('.legend-item')
            .data(legendItems)
            .enter().append('g')
            .attr('class', 'legend-item')
            .attr('transform', (d, i) => `translate(0, ${i * 25})`);

        legendItem.append('circle')
            .attr('r', 8)
            .attr('fill', d => d.color);

        legendItem.append('text')
            .attr('x', 20)
            .attr('y', 5)
            .attr('font-size', '12px')
            .text(d => d.label);
    }

    zoom(factor) {
        const newTransform = d3.zoomIdentity
            .translate(this.transform.x, this.transform.y)
            .scale(this.transform.k * factor);

        this.svg.transition()
            .duration(300)
            .call(this.zoomBehavior.transform, newTransform);
    }

    reset() {
        // Reset zoom
        this.svg.transition()
            .duration(300)
            .call(this.zoomBehavior.transform, d3.zoomIdentity);

        // Clear data
        this.nodes = [];
        this.links = [];

        // Clear visualization
        this.container.selectAll('.link').remove();
        this.container.selectAll('.node').remove();

        // Stop simulation
        if (this.simulation) {
            this.simulation.stop();
        }
    }

    handleResize() {
        const container = this.svg.node().parentElement;
        this.width = container.clientWidth;
        this.height = container.clientHeight;

        // Update center force
        if (this.simulation) {
            this.simulation.force('center', d3.forceCenter(this.width / 2, this.height / 2));
            this.simulation.alpha(0.3).restart();
        }
    }

    // Export graph as image
    exportImage(format = 'png') {
        const svgElement = this.svg.node();
        const serializer = new XMLSerializer();
        const svgString = serializer.serializeToString(svgElement);

        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        const image = new Image();

        canvas.width = this.width;
        canvas.height = this.height;

        image.onload = () => {
            context.fillStyle = 'white';
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.drawImage(image, 0, 0);

            canvas.toBlob(blob => {
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.download = `graph-${Date.now()}.${format}`;
                link.href = url;
                link.click();
                URL.revokeObjectURL(url);
            });
        };

        image.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgString)));
    }
}
