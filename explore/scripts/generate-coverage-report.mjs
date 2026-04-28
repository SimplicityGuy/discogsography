#!/usr/bin/env node
// Generate an lcov.info report from Istanbul coverage data dumped to .nyc_output
// during E2E tests. Replaces `npx nyc report --reporter=lcov ...` plus the
// post-process perl path rewrite.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CoverageReport } from 'monocart-coverage-reports';

const __dirname = dirname(fileURLToPath(import.meta.url));
const exploreDir = resolve(__dirname, '..');
const repoRoot = resolve(exploreDir, '..');
const inputDir = resolve(repoRoot, '.nyc_output');
const outputDir = resolve(exploreDir, 'coverage-e2e');

let entries;
try {
    entries = readdirSync(inputDir).filter((f) => f.endsWith('.json'));
} catch (err) {
    if (err.code === 'ENOENT') {
        console.log(`No coverage input at ${inputDir} — skipping report generation`);
        process.exit(0);
    }
    throw err;
}

if (entries.length === 0) {
    console.log(`No coverage files in ${inputDir} — skipping report generation`);
    process.exit(0);
}

const mcr = new CoverageReport({
    name: 'Explore E2E Coverage',
    outputDir,
    reports: [['lcovonly', { file: 'lcov.info' }]],
    // Rewrite source paths so SF: lines are repo-relative for Codecov
    // (e.g. `/abs/path/explore/static/js/auth.js` -> `explore/static/js/auth.js`).
    sourcePath: (filePath) => {
        const abs = resolve(filePath);
        if (abs.startsWith(repoRoot + '/')) {
            return relative(repoRoot, abs);
        }
        return filePath;
    },
    cleanCache: true,
    logging: 'info',
});

for (const file of entries) {
    const fullPath = join(inputDir, file);
    if (!statSync(fullPath).isFile()) continue;
    const data = JSON.parse(readFileSync(fullPath, 'utf8'));
    await mcr.add(data);
}

const results = await mcr.generate();
if (!results) {
    console.error('No coverage report generated');
    process.exit(1);
}
console.log(`✅ Coverage report generated at ${outputDir}/lcov.info`);
