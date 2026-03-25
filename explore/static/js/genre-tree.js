class GenreTreeView {
    constructor() {
        this._loaded = false;
    }

    async load() {
        const container = document.getElementById('genreTreeContainer');
        if (!container) return;
        if (this._loaded) return; // Don't reload every pane switch

        container.textContent = '';
        const loadingMsg = document.createElement('p');
        loadingMsg.className = 'text-text-mid text-sm';
        loadingMsg.textContent = 'Loading genres...';
        container.appendChild(loadingMsg);

        const data = await window.apiClient.getGenreTree();
        if (!data) {
            container.textContent = '';
            const errMsg = document.createElement('p');
            errMsg.className = 'text-text-mid text-sm';
            errMsg.textContent = 'Failed to load genre tree';
            container.appendChild(errMsg);
            return;
        }
        this._renderTree(container, data.genres || []);
        this._loaded = true;
    }

    _renderTree(container, genres) {
        container.textContent = '';
        if (!genres.length) {
            const emptyMsg = document.createElement('p');
            emptyMsg.className = 'text-text-mid text-sm';
            emptyMsg.textContent = 'No genres found';
            container.appendChild(emptyMsg);
            return;
        }
        const tree = document.createElement('div');
        tree.className = 'genre-tree-container';
        genres.forEach(genre => {
            const item = document.createElement('div');
            item.className = 'genre-tree-item';

            const header = document.createElement('div');
            header.className = 'genre-tree-header';
            header.addEventListener('click', () => this._toggleGenre(item));

            const arrow = document.createElement('span');
            arrow.className = 'material-symbols-outlined genre-tree-arrow';
            arrow.textContent = 'chevron_right';

            const nameEl = document.createElement('a');
            nameEl.className = 'genre-tree-name';
            nameEl.href = '#';
            nameEl.textContent = genre.name;
            nameEl.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this._navigateTo(genre.name, 'genre');
            });

            const badge = document.createElement('span');
            badge.className = 'release-count-badge';
            badge.textContent = genre.release_count.toLocaleString();

            header.append(arrow, nameEl, badge);
            item.appendChild(header);

            // Children (styles)
            if (genre.styles?.length) {
                const children = document.createElement('div');
                children.className = 'genre-tree-children';
                genre.styles.forEach(style => {
                    const styleEl = document.createElement('div');
                    styleEl.className = 'genre-tree-style';
                    const styleName = document.createElement('a');
                    styleName.className = 'genre-tree-style-name';
                    styleName.href = '#';
                    styleName.textContent = style.name;
                    styleName.addEventListener('click', (e) => {
                        e.preventDefault();
                        this._navigateTo(style.name, 'style');
                    });
                    const styleBadge = document.createElement('span');
                    styleBadge.className = 'release-count-badge';
                    styleBadge.textContent = style.release_count.toLocaleString();
                    styleEl.append(styleName, styleBadge);
                    children.appendChild(styleEl);
                });
                item.appendChild(children);
            }

            tree.appendChild(item);
        });
        container.appendChild(tree);
    }

    _toggleGenre(item) {
        item.classList.toggle('expanded');
    }

    _navigateTo(name, type) {
        if (window.exploreApp) {
            window.exploreApp._setSearchType(type);
            window.exploreApp._onSearch(name);
            // Switch to explore pane
            window.exploreApp._switchPane('explore');
        }
    }
}

window.genreTreeView = new GenreTreeView();
