/**
 * D3.js force-directed graph visualization.
 */
class GraphVisualization {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.svg = d3.select('#graphSvg');
        this.placeholder = document.getElementById('graphPlaceholder');

        this.nodes = [];
        this.links = [];
        this.simulation = null;
        this.g = null;
        this.zoom = null;

        // Track expanded categories
        this.expandedCategories = new Set();
        this._pendingExpands = 0;

        // Debounce render
        this._renderTimeout = null;

        // Current center entity
        this.centerName = null;
        this.centerType = null;

        // Callbacks
        this.onNodeClick = null;
        this.onNodeExpand = null;
        this.onExpandsComplete = null;

        this._initSvg();
        this._initControls();
    }

    _initSvg() {
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;

        this.svg
            .attr('width', width)
            .attr('height', height);

        // Zoom behavior
        this.zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on('zoom', (event) => {
                this.g.attr('transform', event.transform);
            });

        this.svg.call(this.zoom);

        // Main group for zoom/pan
        this.g = this.svg.append('g');

        // Arrow marker for links
        this.svg.append('defs').append('marker')
            .attr('id', 'arrowhead')
            .attr('viewBox', '-0 -5 10 10')
            .attr('refX', 20)
            .attr('refY', 0)
            .attr('orient', 'auto')
            .attr('markerWidth', 6)
            .attr('markerHeight', 6)
            .append('path')
            .attr('d', 'M 0,-5 L 10,0 L 0,5')
            .attr('fill', '#2d3051');

        // Handle resize
        window.addEventListener('resize', () => this._onResize());
    }

    _initControls() {
        document.getElementById('zoomInBtn').addEventListener('click', () => this.zoomIn());
        document.getElementById('zoomOutBtn').addEventListener('click', () => this.zoomOut());
        document.getElementById('zoomResetBtn').addEventListener('click', () => this.zoomReset());
        document.getElementById('fullscreenBtn').addEventListener('click', () => this.toggleFullscreen());

        // Escape key exits fullscreen
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.container.classList.contains('fullscreen')) {
                this.toggleFullscreen();
            }
        });
    }

    zoomIn() {
        this.svg.transition().duration(300).call(this.zoom.scaleBy, 1.4);
    }

    zoomOut() {
        this.svg.transition().duration(300).call(this.zoom.scaleBy, 0.7);
    }

    zoomReset() {
        this.svg.transition().duration(300).call(this.zoom.transform, d3.zoomIdentity);
    }

    toggleFullscreen() {
        const isFullscreen = this.container.classList.toggle('fullscreen');
        const icon = document.querySelector('#fullscreenBtn i');
        icon.className = isFullscreen ? 'fas fa-compress' : 'fas fa-expand';
        setTimeout(() => this._onResize(), 50);
    }

    _onResize() {
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;
        this.svg.attr('width', width).attr('height', height);
        if (this.simulation) {
            this.simulation.force('center', d3.forceCenter(width / 2, height / 2));
            this.simulation.alpha(0.3).restart();
        }
    }

    _getNodeRadius(node) {
        if (node.isCenter) return 28;
        if (node.isCategory) return 22;
        return 14;
    }

    /**
     * Set explore data (center + categories).
     * Returns a promise that resolves when all expansions are complete.
     */
    setExploreData(data) {
        // Stop any existing simulation
        if (this.simulation) {
            this.simulation.stop();
            this.simulation = null;
        }

        this.placeholder.classList.add('hidden');
        this.nodes = [];
        this.links = [];
        this.expandedCategories.clear();
        this._pendingExpands = 0;

        // Reset zoom to identity
        this.svg.call(this.zoom.transform, d3.zoomIdentity);

        const center = data.center;
        this.centerName = center.name;
        this.centerType = center.type;

        const width = this.container.clientWidth;
        const height = this.container.clientHeight;

        // Center node
        const centerNode = {
            id: `center-${center.id}`,
            name: center.name,
            type: center.type,
            isCenter: true,
            isCategory: false,
            fx: width / 2,
            fy: height / 2,
        };
        this.nodes.push(centerNode);

        // Category nodes
        const expandable = [];
        data.categories.forEach(cat => {
            const catNode = {
                id: cat.id,
                name: `${cat.name} (${cat.count})`,
                displayName: cat.name,
                type: 'category',
                isCenter: false,
                isCategory: true,
                category: cat.category,
                count: cat.count,
                parentName: center.name,
                parentType: center.type,
            };
            this.nodes.push(catNode);
            this.links.push({ source: centerNode.id, target: catNode.id });
            if (cat.count > 0) {
                expandable.push(cat);
            }
        });

        if (expandable.length === 0) {
            // Nothing to expand, render immediately
            this._render();
            return;
        }

        // Expand all categories concurrently, render once when all are done
        this._pendingExpands = expandable.length;
        expandable.forEach(cat => {
            this._expandCategory(cat.id, center.name, center.type, cat.category);
        });
    }

    async _expandCategory(categoryId, parentName, parentType, category) {
        if (this.expandedCategories.has(categoryId)) {
            this._pendingExpands--;
            this._checkExpandsDone();
            return;
        }
        this.expandedCategories.add(categoryId);

        try {
            const children = await window.apiClient.expand(parentName, parentType, category, 30);

            children.forEach(child => {
                const childId = `child-${child.type}-${child.id}`;
                if (this.nodes.find(n => n.id === childId)) return;

                this.nodes.push({
                    id: childId,
                    name: child.name,
                    type: child.type,
                    isCenter: false,
                    isCategory: false,
                    nodeId: String(child.id),
                });
                this.links.push({ source: categoryId, target: childId });
            });
        } finally {
            this._pendingExpands--;
            this._checkExpandsDone();
        }
    }

    _checkExpandsDone() {
        if (this._pendingExpands <= 0) {
            this._render();
            if (this.onExpandsComplete) {
                this.onExpandsComplete();
            }
        }
    }

    _render() {
        // Cancel any pending debounced render
        if (this._renderTimeout) {
            clearTimeout(this._renderTimeout);
            this._renderTimeout = null;
        }

        // Stop old simulation
        if (this.simulation) {
            this.simulation.stop();
        }

        const width = this.container.clientWidth;
        const height = this.container.clientHeight;

        // Clear previous elements
        this.g.selectAll('*').remove();

        // Create fresh link/node data copies for D3
        // (D3 mutates these objects, so use the existing arrays directly)
        this.simulation = d3.forceSimulation(this.nodes)
            .force('link', d3.forceLink(this.links).id(d => d.id).distance(d => {
                if (d.source.isCenter || d.target.isCenter) return 120;
                if (d.source.isCategory || d.target.isCategory) return 80;
                return 60;
            }))
            .force('charge', d3.forceManyBody().strength(d => {
                if (d.isCenter) return -400;
                if (d.isCategory) return -200;
                return -80;
            }))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(d => this._getNodeRadius(d) + 5));

        // Links
        const link = this.g.append('g')
            .selectAll('line')
            .data(this.links)
            .join('line')
            .attr('class', 'link')
            .attr('stroke-width', 1);

        // Node groups
        const node = this.g.append('g')
            .selectAll('g')
            .data(this.nodes)
            .join('g')
            .style('cursor', 'pointer')
            .call(d3.drag()
                .on('start', (event, d) => this._dragStarted(event, d))
                .on('drag', (event, d) => this._dragged(event, d))
                .on('end', (event, d) => this._dragEnded(event, d)))
            .on('click', (event, d) => this._onNodeClicked(event, d))
            .on('dblclick', (event, d) => this._onNodeDblClicked(event, d));

        // Node shapes
        node.each(function(d) {
            const el = d3.select(this);
            const radius = d.isCenter ? 28 : d.isCategory ? 22 : 14;

            if (d.isCategory) {
                el.append('rect')
                    .attr('x', -radius)
                    .attr('y', -radius * 0.7)
                    .attr('width', radius * 2)
                    .attr('height', radius * 1.4)
                    .attr('rx', 6)
                    .attr('ry', 6)
                    .attr('fill', 'var(--node-category)')
                    .attr('stroke', '#fff')
                    .attr('stroke-width', 1.5);
            } else {
                el.append('circle')
                    .attr('r', radius)
                    .attr('fill', d.isCenter ? 'var(--node-' + d.type + ')' :
                        d.type === 'artist' ? 'var(--node-artist)' :
                        d.type === 'release' ? 'var(--node-release)' :
                        d.type === 'label' ? 'var(--node-label)' :
                        d.type === 'genre' || d.type === 'style' ? 'var(--node-genre)' : '#888')
                    .attr('stroke', d.isCenter ? '#fff' : 'rgba(255,255,255,0.3)')
                    .attr('stroke-width', d.isCenter ? 3 : 1);
            }
        });

        // Labels
        node.append('text')
            .attr('class', 'node-label')
            .attr('dy', d => d.isCategory ? 0 : this._getNodeRadius(d) + 14)
            .text(d => {
                const name = d.displayName || d.name;
                return name.length > 20 ? name.substring(0, 18) + '...' : name;
            })
            .style('font-size', d => d.isCenter ? '13px' : d.isCategory ? '11px' : '10px')
            .style('font-weight', d => d.isCenter ? '700' : '400');

        // Simulation tick
        this.simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });
    }

    _dragStarted(event, d) {
        if (!event.active) this.simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    _dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    _dragEnded(event, d) {
        if (!event.active) this.simulation.alphaTarget(0);
        if (!d.isCenter) {
            d.fx = null;
            d.fy = null;
        }
    }

    _onNodeClicked(event, d) {
        event.stopPropagation();
        if (d.isCategory) return;

        if (this.onNodeClick) {
            const nodeId = d.nodeId || d.name;
            this.onNodeClick(nodeId, d.type);
        }
    }

    _onNodeDblClicked(event, d) {
        event.stopPropagation();
        event.preventDefault();
        if (d.isCategory || d.isCenter) return;

        if (this.onNodeExpand) {
            this.onNodeExpand(d.name, d.type);
        }
    }

    clear() {
        this.nodes = [];
        this.links = [];
        this.expandedCategories.clear();
        this.g.selectAll('*').remove();
        if (this.simulation) {
            this.simulation.stop();
            this.simulation = null;
        }
        this.placeholder.classList.remove('hidden');
    }
}
