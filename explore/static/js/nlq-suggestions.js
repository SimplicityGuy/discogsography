const STORAGE_KEY = 'nlq.history';
const HISTORY_CAP = 5;

export class NlqSuggestions {
    constructor({ container, fetchFn, onPick = null }) {
        this.container = container;
        this.fetchFn = fetchFn;
        this.onPick = onPick;
    }

    async render({ pane, focus = null, focusType = null }) {
        this._clear();
        let suggestions = [];
        try {
            const result = await this.fetchFn({ pane, focus, focusType });
            suggestions = result?.suggestions ?? [];
        } catch (err) {
            console.warn('🤷 NLQ suggestions fetch failed', err);
        }
        this._renderChipRow('Suggested for you', suggestions, 'nlq-suggestion-chip');
        const recent = NlqSuggestions.loadRecent();
        this._renderChipRow('Recent', recent, 'nlq-recent-chip');
    }

    _clear() {
        while (this.container.firstChild) this.container.removeChild(this.container.firstChild);
    }

    _renderChipRow(label, items, testId) {
        if (!items || items.length === 0) return;
        const row = document.createElement('div');
        row.className = 'nlq-chip-row';
        const heading = document.createElement('div');
        heading.className = 'nlq-chip-label';
        heading.textContent = label;
        row.appendChild(heading);
        for (const text of items) {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'nlq-chip';
            chip.setAttribute('data-testid', testId);
            chip.textContent = text;
            chip.addEventListener('click', () => {
                if (this.onPick) this.onPick(text);
            });
            row.appendChild(chip);
        }
        this.container.appendChild(row);
    }

    static loadRecent() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) {
                localStorage.removeItem(STORAGE_KEY);
                console.info('ℹ️ NLQ history reset (not an array)');
                return [];
            }
            return parsed;
        } catch {
            localStorage.removeItem(STORAGE_KEY);
            console.info('ℹ️ NLQ history reset (corrupt)');
            return [];
        }
    }

    static addRecent(query) {
        const trimmed = (query ?? '').trim();
        if (!trimmed) return;
        const current = NlqSuggestions.loadRecent().filter((q) => q !== trimmed);
        current.unshift(trimmed);
        const capped = current.slice(0, HISTORY_CAP);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(capped));
    }
}
