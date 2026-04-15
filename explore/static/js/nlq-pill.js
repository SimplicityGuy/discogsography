/**
 * Global floating Ask pill — state machine: collapsed → expanded → loading → summary.
 */

export class NlqPill {
    constructor({ mountId = 'nlqPillMount' } = {}) {
        this.mountId = mountId;
        this.state = 'collapsed';
        this.root = null;
    }

    mount() {
        const mount = document.getElementById(this.mountId);
        if (!mount) return;
        this.root = document.createElement('div');
        this.root.className = 'nlq-pill-root';
        mount.appendChild(this.root);
        this._render();
    }

    _render() {
        if (!this.root) return;
        while (this.root.firstChild) this.root.removeChild(this.root.firstChild);
        if (this.state === 'collapsed') {
            this._renderCollapsed();
        }
    }

    _renderCollapsed() {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.setAttribute('data-testid', 'nlq-pill-collapsed');
        pill.className = 'nlq-pill-collapsed';
        const sparkle = document.createElement('span');
        sparkle.className = 'nlq-pill-sparkle';
        sparkle.textContent = '✨';
        const label = document.createElement('span');
        label.textContent = ' Ask the graph ';
        const kbd = document.createElement('kbd');
        kbd.textContent = '⌘K';
        pill.appendChild(sparkle);
        pill.appendChild(label);
        pill.appendChild(kbd);
        this.root.appendChild(pill);
    }
}
