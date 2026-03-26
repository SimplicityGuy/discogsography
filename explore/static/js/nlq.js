/**
 * NLQ (Natural Language Query) panel controller.
 * Provides an "Ask" interface for natural language questions about the music graph.
 */
class NLQPanel {
    constructor() {
        this.panel = document.getElementById('nlqPanel');
        this.input = document.getElementById('nlqInput');
        this.submitBtn = document.getElementById('nlqSubmit');
        this.statusEl = document.getElementById('nlqStatus');
        this.resultEl = document.getElementById('nlqResult');
        this.examplesEl = document.getElementById('nlqExamples');

        /** @type {Function|null} Callback: (name, type) => void */
        this.onExploreEntity = null;

        this._bindEvents();
    }

    /**
     * Check if NLQ is enabled on the server.
     * @returns {Promise<boolean>} true if NLQ is enabled
     */
    async checkEnabled() {
        const status = await window.apiClient.checkNlqStatus();
        return status && status.enabled === true;
    }

    /** Show the NLQ panel. */
    show() {
        if (this.panel) this.panel.style.display = '';
    }

    /** Hide the NLQ panel. */
    hide() {
        if (this.panel) this.panel.style.display = 'none';
    }

    /** Bind DOM event listeners. */
    _bindEvents() {
        if (this.submitBtn) {
            this.submitBtn.addEventListener('click', () => this._submit());
        }
        if (this.input) {
            this.input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') this._submit();
            });
        }
        if (this.examplesEl) {
            this.examplesEl.addEventListener('click', (e) => {
                const btn = e.target.closest('[data-nlq-example]');
                if (btn) {
                    const query = btn.getAttribute('data-nlq-example');
                    if (this.input) this.input.value = query;
                    this._submit();
                }
            });
        }
    }

    /** Submit the current query. */
    _submit() {
        const query = this.input ? this.input.value.trim() : '';
        if (!query) return;

        this._setLoading(true);
        this._clearResult();

        window.apiClient.askNlqStream(
            query,
            null,
            (statusData) => this._showStatus(statusData),
            (resultData) => {
                this._setLoading(false);
                this._showResult(resultData);
            },
            (err) => {
                this._setLoading(false);
                this._showError(err);
            },
        );
    }

    /** Toggle loading state. */
    _setLoading(loading) {
        if (this.submitBtn) this.submitBtn.disabled = loading;
        if (this.input) this.input.disabled = loading;
    }

    /** Clear previous results. */
    _clearResult() {
        if (this.resultEl) {
            while (this.resultEl.firstChild) {
                this.resultEl.removeChild(this.resultEl.firstChild);
            }
        }
        if (this.statusEl) {
            this.statusEl.style.display = 'none';
            this.statusEl.textContent = '';
        }
    }

    /** Show a status message (from SSE status events). */
    _showStatus(data) {
        if (!this.statusEl) return;
        this.statusEl.style.display = '';
        this.statusEl.textContent = data.message || data.step || 'Thinking...';
    }

    /**
     * Render the result using safe DOM methods (no innerHTML).
     * @param {Object} data - Result data with summary, entities, tools_used
     */
    _showResult(data) {
        if (this.statusEl) this.statusEl.style.display = 'none';
        if (!this.resultEl) return;

        // Clear existing content
        while (this.resultEl.firstChild) {
            this.resultEl.removeChild(this.resultEl.firstChild);
        }

        if (!data || !data.summary) {
            const noResult = document.createElement('p');
            noResult.textContent = 'No answer received. Please try again.';
            noResult.className = 'text-text-low italic';
            this.resultEl.appendChild(noResult);
            return;
        }

        // Build summary paragraph with entity links
        const summaryP = document.createElement('p');
        const entities = data.entities || [];
        let summaryText = data.summary;

        if (entities.length > 0) {
            // Build entity-linked summary using safe DOM methods
            const fragments = this._buildEntityLinkedText(summaryText, entities);
            for (const fragment of fragments) {
                summaryP.appendChild(fragment);
            }
        } else {
            summaryP.textContent = summaryText;
        }
        this.resultEl.appendChild(summaryP);

        // Tools used pills
        const toolsUsed = data.tools_used || [];
        if (toolsUsed.length > 0) {
            const toolsDiv = document.createElement('div');
            for (const tool of toolsUsed) {
                const pill = document.createElement('span');
                pill.className = 'nlq-tool-pill';
                pill.textContent = tool;
                toolsDiv.appendChild(pill);
            }
            this.resultEl.appendChild(toolsDiv);
        }

        // Cached indicator
        if (data.cached) {
            const cachedSpan = document.createElement('span');
            cachedSpan.className = 'text-xs text-text-low italic';
            cachedSpan.textContent = ' (cached)';
            this.resultEl.appendChild(cachedSpan);
        }
    }

    /**
     * Build an array of DOM nodes (text nodes and <a> elements) from summary text,
     * linking entity names found within the text.
     * @param {string} text - The summary text
     * @param {Array<{name: string, type: string}>} entities - Entities to link
     * @returns {Array<Node>} Array of text nodes and anchor elements
     */
    _buildEntityLinkedText(text, entities) {
        // Sort entities by name length descending to match longer names first
        const sorted = [...entities].sort((a, b) => (b.name || '').length - (a.name || '').length);

        // Find all entity occurrences in the text
        const matches = [];
        for (const entity of sorted) {
            if (!entity.name) continue;
            let searchFrom = 0;
            while (searchFrom < text.length) {
                const idx = text.indexOf(entity.name, searchFrom);
                if (idx === -1) break;
                // Check no overlap with existing matches
                const end = idx + entity.name.length;
                const overlaps = matches.some(m => idx < m.end && end > m.start);
                if (!overlaps) {
                    matches.push({ start: idx, end, entity });
                }
                searchFrom = idx + 1;
            }
        }

        // Sort matches by position
        matches.sort((a, b) => a.start - b.start);

        const nodes = [];
        let cursor = 0;
        for (const match of matches) {
            // Text before this match
            if (match.start > cursor) {
                nodes.push(document.createTextNode(text.slice(cursor, match.start)));
            }
            // Entity link
            const link = document.createElement('a');
            link.textContent = match.entity.name;
            link.className = 'nlq-entity-link';
            link.setAttribute('data-entity-name', match.entity.name);
            link.setAttribute('data-entity-type', match.entity.type || 'artist');
            link.setAttribute('href', '#');
            link.addEventListener('click', (e) => {
                e.preventDefault();
                if (this.onExploreEntity) {
                    this.onExploreEntity(match.entity.name, match.entity.type || 'artist');
                }
            });
            nodes.push(link);
            cursor = match.end;
        }
        // Remaining text
        if (cursor < text.length) {
            nodes.push(document.createTextNode(text.slice(cursor)));
        }

        return nodes;
    }

    /** Show an error message. */
    _showError(err) {
        if (this.statusEl) this.statusEl.style.display = 'none';
        if (!this.resultEl) return;

        while (this.resultEl.firstChild) {
            this.resultEl.removeChild(this.resultEl.firstChild);
        }

        const errorP = document.createElement('p');
        errorP.className = 'text-red-400 text-sm';
        if (typeof err === 'number') {
            errorP.textContent = err === 503
                ? 'NLQ service is currently unavailable.'
                : `Request failed (status ${err}).`;
        } else {
            errorP.textContent = 'Unable to reach the server. Please try again.';
        }
        this.resultEl.appendChild(errorP);
    }
}

// Export for use in app.js
window.NLQPanel = NLQPanel;
