#!/usr/bin/env node
// Instrument JS files in static/js/ in-place for browser-side coverage during E2E tests.
// Replaces `npx nyc instrument --in-place static/js`.

import { readFileSync, statSync, writeFileSync, readdirSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createInstrumenter } from 'istanbul-lib-instrument';

const __dirname = dirname(fileURLToPath(import.meta.url));
const targetDir = resolve(__dirname, '..', 'static', 'js');

const instrumenter = createInstrumenter({
    esModules: true,
    produceSourceMap: false,
    compact: false,
    preserveComments: true,
    coverageVariable: '__coverage__',
});

function walk(dir) {
    const entries = readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) {
            walk(full);
        } else if (entry.isFile() && entry.name.endsWith('.js')) {
            instrumentFile(full);
        }
    }
}

function instrumentFile(file) {
    const code = readFileSync(file, 'utf8');
    const instrumented = instrumenter.instrumentSync(code, file);
    writeFileSync(file, instrumented, 'utf8');
}

statSync(targetDir);
walk(targetDir);
console.log(`Instrumented JS files under ${targetDir}`);
