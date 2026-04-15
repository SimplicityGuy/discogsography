import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'app.js'), 'utf8');

describe('legacy NLQ navbar removed', () => {
    it('index.html has no searchAskToggle', () => {
        expect(indexHtml).not.toContain('searchAskToggle');
    });

    it('index.html has no nlqPanel in the navbar', () => {
        expect(indexHtml).not.toContain('id="nlqPanel"');
    });

    it('index.html has no hardcoded nlqExamples', () => {
        expect(indexHtml).not.toContain('id="nlqExamples"');
    });

    it('app.js has no searchModeBtn handler', () => {
        expect(appJs).not.toContain('searchModeBtn');
    });
});
