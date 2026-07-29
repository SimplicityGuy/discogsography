import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadScript } from './helpers.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * Set up the DOM elements required by theme.js.
 */
function setupThemeDOM() {
    document.body.textContent = '';
    document.documentElement.className = '';

    const btn = document.createElement('button');
    btn.id = 'theme-toggle';
    document.body.appendChild(btn);

    const auto = document.createElement('span');
    auto.id = 'theme-icon-auto';
    document.body.appendChild(auto);

    const sun = document.createElement('span');
    sun.id = 'theme-icon-sun';
    document.body.appendChild(sun);

    const moon = document.createElement('span');
    moon.id = 'theme-icon-moon';
    document.body.appendChild(moon);
}

describe('theme toggle (tri-state)', () => {
    beforeEach(() => {
        setupThemeDOM();
        localStorage.clear();
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

    it('should default to auto mode with auto icon visible', () => {
        loadScript('theme.js');

        const auto = document.getElementById('theme-icon-auto');
        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        expect(auto.classList.contains('hidden')).toBe(false);
        expect(sun.classList.contains('hidden')).toBe(true);
        expect(moon.classList.contains('hidden')).toBe(true);
    });

    it('should show sun icon when theme is explicitly light', () => {
        localStorage.setItem('theme', 'light');
        loadScript('theme.js');

        const auto = document.getElementById('theme-icon-auto');
        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        expect(auto.classList.contains('hidden')).toBe(true);
        expect(sun.classList.contains('hidden')).toBe(false);
        expect(moon.classList.contains('hidden')).toBe(true);
    });

    it('should show moon icon when theme is explicitly dark', () => {
        localStorage.setItem('theme', 'dark');
        loadScript('theme.js');

        const auto = document.getElementById('theme-icon-auto');
        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        expect(auto.classList.contains('hidden')).toBe(true);
        expect(sun.classList.contains('hidden')).toBe(true);
        expect(moon.classList.contains('hidden')).toBe(false);
    });

    it('should cycle auto → light → dark → auto on clicks', () => {
        loadScript('theme.js');
        const btn = document.getElementById('theme-toggle');

        // Start: auto
        expect(localStorage.getItem('theme')).toBeNull();

        // Click 1: auto → light
        btn.click();
        expect(localStorage.getItem('theme')).toBe('light');
        expect(document.documentElement.classList.contains('dark')).toBe(false);

        // Click 2: light → dark
        btn.click();
        expect(localStorage.getItem('theme')).toBe('dark');
        expect(document.documentElement.classList.contains('dark')).toBe(true);

        // Click 3: dark → auto (removes from storage)
        btn.click();
        expect(localStorage.getItem('theme')).toBeNull();
    });

    it('should apply OS dark preference when in auto mode', () => {
        const listeners = [];
        globalThis.window.matchMedia = vi.fn((query) => ({
            matches: query.includes('dark'),
            addEventListener: (event, cb) => { listeners.push(cb); },
            removeEventListener: vi.fn(),
        }));

        loadScript('theme.js');

        // In auto mode with OS dark preference, should be dark
        expect(document.documentElement.classList.contains('dark')).toBe(true);

        // Simulate OS switching to light
        listeners.forEach(cb => cb({ matches: false }));
        expect(document.documentElement.classList.contains('dark')).toBe(false);
    });

    it('should NOT apply OS preference change when theme is explicitly set', () => {
        localStorage.setItem('theme', 'light');

        const listeners = [];
        globalThis.window.matchMedia = vi.fn((query) => ({
            matches: false,
            addEventListener: (event, cb) => { listeners.push(cb); },
            removeEventListener: vi.fn(),
        }));

        loadScript('theme.js');

        // OS says dark, but stored preference should prevent change
        listeners.forEach(cb => cb({ matches: true }));
        expect(document.documentElement.classList.contains('dark')).toBe(false);
    });

    it('should update icons correctly through the cycle', () => {
        loadScript('theme.js');
        const btn = document.getElementById('theme-toggle');
        const auto = document.getElementById('theme-icon-auto');
        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');

        // auto mode
        expect(auto.classList.contains('hidden')).toBe(false);

        // → light
        btn.click();
        expect(auto.classList.contains('hidden')).toBe(true);
        expect(sun.classList.contains('hidden')).toBe(false);
        expect(moon.classList.contains('hidden')).toBe(true);

        // → dark
        btn.click();
        expect(auto.classList.contains('hidden')).toBe(true);
        expect(sun.classList.contains('hidden')).toBe(true);
        expect(moon.classList.contains('hidden')).toBe(false);

        // → auto
        btn.click();
        expect(auto.classList.contains('hidden')).toBe(false);
        expect(sun.classList.contains('hidden')).toBe(true);
        expect(moon.classList.contains('hidden')).toBe(true);
    });

    it('should not crash when required DOM elements are missing', () => {
        document.body.textContent = '';
        expect(() => loadScript('theme.js')).not.toThrow();
    });

    it('should apply a persisted preference even when the toggle button markup is absent', () => {
        // Regression: previously applyMode() was gated behind the toggle
        // button + icon spans existing, so a stored preference was silently
        // ignored whenever that markup was missing.
        document.body.textContent = '';
        localStorage.setItem('theme', 'dark');

        loadScript('theme.js');

        expect(document.documentElement.classList.contains('dark')).toBe(true);
    });

    it('should apply the OS dark preference in auto mode even when the toggle button markup is absent', () => {
        document.body.textContent = '';
        globalThis.window.matchMedia = vi.fn((query) => ({
            matches: query.includes('dark'),
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        }));

        loadScript('theme.js');

        expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
});

describe('theme toggle markup', () => {
    it('index.html wires up the #theme-toggle button and icon spans theme.js requires', () => {
        const html = readFileSync(resolve(__dirname, '..', 'static', 'index.html'), 'utf-8');

        expect(html).toContain('id="theme-toggle"');
        expect(html).toContain('id="theme-icon-auto"');
        expect(html).toContain('id="theme-icon-sun"');
        expect(html).toContain('id="theme-icon-moon"');
        // The toggle must be included as a real page script for it to run.
        expect(html).toContain('js/theme.js');
    });
});
