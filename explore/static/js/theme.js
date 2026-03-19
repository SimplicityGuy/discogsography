/**
 * Theme toggle — tri-state: auto (match OS, default) → light → dark.
 * Matches dashboard implementation.
 */
(function initThemeToggle() {
    'use strict';

    const btn = document.getElementById('theme-toggle');
    const autoIcon = document.getElementById('theme-icon-auto');
    const sunIcon = document.getElementById('theme-icon-sun');
    const moonIcon = document.getElementById('theme-icon-moon');
    if (!btn || !autoIcon || !sunIcon || !moonIcon) return;

    function getMode() {
        return localStorage.getItem('theme') || 'auto';
    }

    function applyMode(mode) {
        if (mode === 'auto') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.documentElement.classList.toggle('dark', prefersDark);
        } else {
            document.documentElement.classList.toggle('dark', mode === 'dark');
        }
    }

    function updateIcons() {
        const mode = getMode();
        autoIcon.classList.toggle('hidden', mode !== 'auto');
        sunIcon.classList.toggle('hidden', mode !== 'light');
        moonIcon.classList.toggle('hidden', mode !== 'dark');
    }

    applyMode(getMode());
    updateIcons();

    const cycle = { auto: 'light', light: 'dark', dark: 'auto' };

    btn.addEventListener('click', () => {
        const next = cycle[getMode()];
        if (next === 'auto') {
            localStorage.removeItem('theme');
        } else {
            localStorage.setItem('theme', next);
        }
        applyMode(next);
        updateIcons();
    });

    // Listen for OS-level theme changes — only applies when in auto mode
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (getMode() === 'auto') {
            document.documentElement.classList.toggle('dark', e.matches);
        }
    });
})();
