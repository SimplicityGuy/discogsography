import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const staticDir = path.join(__dirname, '..', 'static');
const jsDir = path.join(staticDir, 'js');
const indexHtml = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');

function extractImportMap(html) {
    const match = html.match(/<script\s+type="importmap"[^>]*>([\s\S]*?)<\/script>/);
    if (!match) return {};
    const parsed = JSON.parse(match[1]);
    return parsed.imports || {};
}

function findBareSpecifiers(source) {
    const specifiers = [];
    const pattern = /(?:^|\s|;)import\s+(?:[^'"\n]+?\s+from\s+)?['"]([^'"\n]+)['"]/g;
    let match;
    while ((match = pattern.exec(source)) !== null) {
        const specifier = match[1];
        const isRelative = specifier.startsWith('./') || specifier.startsWith('../') || specifier.startsWith('/');
        const isUrl = /^https?:/i.test(specifier);
        if (isRelative || isUrl) continue;
        specifiers.push(specifier);
    }
    return specifiers;
}

function collectBareSpecifiers(dir) {
    const out = new Map();
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
            for (const [spec, files] of collectBareSpecifiers(path.join(dir, entry.name))) {
                const existing = out.get(spec) ?? [];
                out.set(spec, [...existing, ...files]);
            }
            continue;
        }
        if (!entry.name.endsWith('.js') && !entry.name.endsWith('.mjs')) continue;
        const full = path.join(dir, entry.name);
        const source = fs.readFileSync(full, 'utf8');
        for (const specifier of findBareSpecifiers(source)) {
            const existing = out.get(specifier) ?? [];
            out.set(specifier, [...existing, path.relative(jsDir, full)]);
        }
    }
    return out;
}

describe('importmap covers all bare module specifiers in static/js', () => {
    it('every bare specifier imported by static JS is declared in index.html importmap', () => {
        const imports = extractImportMap(indexHtml);
        const mapped = new Set(Object.keys(imports));
        const bareSpecs = collectBareSpecifiers(jsDir);
        const missing = [];
        for (const [spec, files] of bareSpecs) {
            if (!mapped.has(spec)) missing.push({ spec, files });
        }
        expect(missing, `bare specifiers missing from importmap: ${JSON.stringify(missing, null, 2)}`).toEqual([]);
    });

    it('importmap is defined before the first <script type="module">', () => {
        const importMapIdx = indexHtml.indexOf('<script type="importmap"');
        const firstModuleIdx = indexHtml.indexOf('<script type="module"');
        expect(importMapIdx, 'importmap missing from index.html').toBeGreaterThanOrEqual(0);
        expect(firstModuleIdx, 'no module script found').toBeGreaterThanOrEqual(0);
        expect(importMapIdx).toBeLessThan(firstModuleIdx);
    });
});
