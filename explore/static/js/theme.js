/**
 * Theme toggle — light/dark mode with OS preference detection.
 * Matches dashboard implementation.
 */
(function initThemeToggle() {
    'use strict';

    const btn = document.getElementById('theme-toggle');
    const sunIcon = document.getElementById('theme-icon-sun');
    const moonIcon = document.getElementById('theme-icon-moon');
    if (!btn || !sunIcon || !moonIcon) return;

    function updateIcons() {
        const isDark = document.documentElement.classList.contains('dark');
        sunIcon.classList.toggle('hidden', isDark);
        moonIcon.classList.toggle('hidden', !isDark);
    }

    updateIcons();

    btn.addEventListener('click', () => {
        const isDark = document.documentElement.classList.toggle('dark');
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
        updateIcons();
    });

    // Listen for OS-level theme changes when no explicit preference is saved
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!localStorage.getItem('theme')) {
            document.documentElement.classList.toggle('dark', e.matches);
            updateIcons();
        }
    });
})();
