import { renderSummary } from './nlq-markdown.js';

export class NlqSummaryStrip {
    constructor({ container, onUndo = null, onEntityClick = null }) {
        this.container = container;
        this.onUndo = onUndo;
        this.onEntityClick = onEntityClick;
    }

    show({ summary, entities, appliedActions, skipped }) {
        this.hide();

        const strip = document.createElement('div');
        strip.setAttribute('data-testid', 'nlq-strip');
        strip.className = 'nlq-summary-strip';

        const summaryEl = document.createElement('div');
        summaryEl.className = 'nlq-summary-text';
        renderSummary(summaryEl, summary, entities, this.onEntityClick);
        strip.appendChild(summaryEl);

        const footer = document.createElement('div');
        footer.className = 'nlq-summary-footer';
        const log = document.createElement('span');
        log.className = 'nlq-action-log';
        const appliedText = (appliedActions || []).map((a) => `✓ ${a}`).join(' • ');
        const skippedText = skipped > 0 ? ` (${skipped} action(s) skipped)` : '';
        log.textContent = appliedText + skippedText;
        footer.appendChild(log);

        if ((appliedActions || []).length > 0 && this.onUndo) {
            const undoBtn = document.createElement('button');
            undoBtn.type = 'button';
            undoBtn.setAttribute('data-testid', 'nlq-strip-undo');
            undoBtn.className = 'nlq-strip-btn';
            undoBtn.textContent = '↶ Undo';
            undoBtn.addEventListener('click', () => this.onUndo());
            footer.appendChild(undoBtn);
        }

        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.setAttribute('data-testid', 'nlq-strip-dismiss');
        dismiss.className = 'nlq-strip-btn';
        dismiss.textContent = '✕';
        dismiss.addEventListener('click', () => this.hide());
        footer.appendChild(dismiss);

        strip.appendChild(footer);
        this.container.appendChild(strip);
    }

    hide() {
        const existing = this.container.querySelector('[data-testid="nlq-strip"]');
        if (existing) existing.remove();
    }
}
