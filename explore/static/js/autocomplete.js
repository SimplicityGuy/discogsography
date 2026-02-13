/**
 * Autocomplete handler with debouncing and keyboard navigation.
 */
class Autocomplete {
    constructor() {
        this.input = document.getElementById('searchInput');
        this.dropdown = document.getElementById('autocompleteDropdown');
        this.debounceTimer = null;
        this.debounceMs = 300;
        this.minChars = 2;
        this.activeIndex = -1;
        this.results = [];
        this.onSelect = null;

        this._bindEvents();
    }

    _bindEvents() {
        this.input.addEventListener('input', () => this._onInput());
        this.input.addEventListener('keydown', (e) => this._onKeydown(e));

        // Close dropdown on outside click
        document.addEventListener('click', (e) => {
            if (!this.input.contains(e.target) && !this.dropdown.contains(e.target)) {
                this.close();
            }
        });
    }

    _onInput() {
        clearTimeout(this.debounceTimer);
        const query = this.input.value.trim();

        if (query.length < this.minChars) {
            this.close();
            return;
        }

        this.debounceTimer = setTimeout(() => this._search(query), this.debounceMs);
    }

    async _search(query) {
        const type = window.exploreApp ? window.exploreApp.searchType : 'artist';
        this.results = await window.apiClient.autocomplete(query, type);
        this.activeIndex = -1;
        this._render();
    }

    _render() {
        if (this.results.length === 0) {
            this.close();
            return;
        }

        this.dropdown.innerHTML = this.results.map((item, index) => `
            <div class="autocomplete-item ${index === this.activeIndex ? 'active' : ''}"
                 data-index="${index}">
                <span class="name">${this._escapeHtml(item.name)}</span>
            </div>
        `).join('');

        // Bind click events
        this.dropdown.querySelectorAll('.autocomplete-item').forEach(el => {
            el.addEventListener('click', () => {
                const idx = parseInt(el.dataset.index);
                this._selectItem(idx);
            });
        });

        this.dropdown.classList.add('show');
    }

    _onKeydown(e) {
        if (!this.dropdown.classList.contains('show')) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const query = this.input.value.trim();
                if (query && this.onSelect) {
                    this.onSelect(query);
                }
            }
            return;
        }

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.activeIndex = Math.min(this.activeIndex + 1, this.results.length - 1);
                this._render();
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.activeIndex = Math.max(this.activeIndex - 1, -1);
                this._render();
                break;
            case 'Enter':
                e.preventDefault();
                if (this.activeIndex >= 0) {
                    this._selectItem(this.activeIndex);
                } else {
                    const query = this.input.value.trim();
                    if (query && this.onSelect) {
                        this.close();
                        this.onSelect(query);
                    }
                }
                break;
            case 'Escape':
                this.close();
                break;
        }
    }

    _selectItem(index) {
        const item = this.results[index];
        if (item) {
            this.input.value = item.name;
            this.close();
            if (this.onSelect) {
                this.onSelect(item.name);
            }
        }
    }

    close() {
        this.dropdown.classList.remove('show');
        this.activeIndex = -1;
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
