import { describe, it, expect, vi, beforeEach } from 'vitest';
import { loadScript } from './helpers.js';

/**
 * Set up the DOM elements required by theme.js.
 */
function setupThemeDOM() {
    document.body.textContent = '';
    document.documentElement.className = '';

    const btn = document.createElement('button');
    btn.id = 'theme-toggle';
    document.body.appendChild(btn);

    const sun = document.createElement('span');
    sun.id = 'theme-icon-sun';
    document.body.appendChild(sun);

    const moon = document.createElement('span');
    moon.id = 'theme-icon-moon';
    document.body.appendChild(moon);
}

describe('theme toggle', () => {
    beforeEach(() => {
        setupThemeDOM();
        localStorage.clear();
        // Remove any existing dark class
        document.documentElement.classList.remove('dark');
        delete globalThis.window;
        globalThis.window = globalThis;

        // Default matchMedia mock (reports no dark preference)
        globalThis.window.matchMedia = vi.fn((query) => ({
            matches: false,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        }));
    });

    it('should initialize with light mode icons when not in dark mode', () => {
        loadScript('theme.js');

        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        // In light mode: sun visible, moon hidden
        expect(sun.classList.contains('hidden')).toBe(false);
        expect(moon.classList.contains('hidden')).toBe(true);
    });

    it('should initialize with dark mode icons when html has dark class', () => {
        document.documentElement.classList.add('dark');
        loadScript('theme.js');

        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        // In dark mode: sun hidden, moon visible
        expect(sun.classList.contains('hidden')).toBe(true);
        expect(moon.classList.contains('hidden')).toBe(false);
    });

    it('should toggle to dark mode on button click', () => {
        loadScript('theme.js');

        const btn = document.getElementById('theme-toggle');
        btn.click();

        expect(document.documentElement.classList.contains('dark')).toBe(true);
        expect(localStorage.getItem('theme')).toBe('dark');
    });

    it('should toggle back to light mode on second click', () => {
        document.documentElement.classList.add('dark');
        loadScript('theme.js');

        const btn = document.getElementById('theme-toggle');
        btn.click();

        expect(document.documentElement.classList.contains('dark')).toBe(false);
        expect(localStorage.getItem('theme')).toBe('light');
    });

    it('should update icons after toggle to dark', () => {
        loadScript('theme.js');

        const btn = document.getElementById('theme-toggle');
        btn.click();

        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        expect(sun.classList.contains('hidden')).toBe(true);
        expect(moon.classList.contains('hidden')).toBe(false);
    });

    it('should update icons after toggle to light', () => {
        document.documentElement.classList.add('dark');
        loadScript('theme.js');

        const btn = document.getElementById('theme-toggle');
        btn.click();

        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        expect(sun.classList.contains('hidden')).toBe(false);
        expect(moon.classList.contains('hidden')).toBe(true);
    });

    it('should not crash when required DOM elements are missing', () => {
        // Remove DOM elements
        document.body.textContent = '';

        // Should return early without throwing
        expect(() => loadScript('theme.js')).not.toThrow();
    });

    it('should apply OS dark preference when no stored theme', () => {
        // Mock matchMedia that reports dark preference
        const listeners = [];
        globalThis.window.matchMedia = vi.fn((query) => ({
            matches: query.includes('dark'),
            addEventListener: (event, cb) => { listeners.push(cb); },
            removeEventListener: vi.fn(),
        }));

        loadScript('theme.js');

        // Simulate OS dark mode change
        listeners.forEach(cb => cb({ matches: true }));

        expect(document.documentElement.classList.contains('dark')).toBe(true);
    });

    it('should NOT apply OS preference change when a theme is explicitly stored', () => {
        localStorage.setItem('theme', 'light');

        const listeners = [];
        globalThis.window.matchMedia = vi.fn((query) => ({
            matches: false,
            addEventListener: (event, cb) => { listeners.push(cb); },
            removeEventListener: vi.fn(),
        }));

        loadScript('theme.js');

        // Even though OS says dark, stored preference should prevent change
        listeners.forEach(cb => cb({ matches: true }));

        // Light theme was stored, so should remain light
        expect(document.documentElement.classList.contains('dark')).toBe(false);
    });
});
