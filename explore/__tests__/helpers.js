import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = resolve(__dirname, '..', 'static', 'js');

/**
 * Load a vanilla JS file into the current jsdom window environment.
 * Wraps the code in an IIFE so that class declarations don't collide
 * across repeated calls (class is lexical, like let/const).
 * The `window.*` assignments inside the file still work because
 * `window` points to `globalThis` in the jsdom environment.
 *
 * @param {string} filename - JS filename relative to explore/static/js/
 */
export function loadScript(filename) {
    const filepath = resolve(STATIC_DIR, filename);
    const code = readFileSync(filepath, 'utf-8');
    // Wrap in IIFE to avoid "already declared" errors on repeated loads
    const wrapped = `(function() {\n${code}\n})();`;
    vm.runInThisContext(wrapped, { filename: filepath });
}

/**
 * Load a vanilla JS file directly into the global scope (no IIFE wrapping).
 * Use this for class-based files where the class needs to be accessible as a
 * global (e.g. `new TrendsChart()`). Only call once per test suite since
 * re-running in the same context will throw "already declared" for class/let/const.
 *
 * @param {string} filename - JS filename relative to explore/static/js/
 */
export function loadScriptDirect(filename) {
    const filepath = resolve(STATIC_DIR, filename);
    const code = readFileSync(filepath, 'utf-8');
    vm.runInThisContext(code, { filename: filepath });
}

/**
 * Create a mock fetch that returns predefined responses.
 * @param {Object} responses - Map of URL patterns to response data
 * @returns {Function} Mock fetch function
 */
export function createMockFetch(responses = {}) {
    return async (url, _options = {}) => {
        const urlStr = typeof url === 'string' ? url : url.toString();

        for (const [pattern, config] of Object.entries(responses)) {
            if (urlStr.includes(pattern)) {
                const status = config.status ?? 200;
                const ok = status >= 200 && status < 300;
                return {
                    ok,
                    status,
                    json: async () => config.data ?? {},
                    blob: async () => config.blob ?? new Blob(),
                };
            }
        }

        // Default: return 404
        return {
            ok: false,
            status: 404,
            json: async () => ({ error: 'Not found' }),
            blob: async () => new Blob(),
        };
    };
}
