import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'app.js'), 'utf8');

describe('NLQ init wiring', () => {
    it('index.html has nlqPillMount', () => {
        expect(indexHtml).toContain('id="nlqPillMount"');
    });

    it('index.html no longer references the legacy nlqStripMount', () => {
        expect(indexHtml).not.toContain('id="nlqStripMount"');
        expect(indexHtml).not.toContain('nlqStripMount');
    });

    it('app.js calls initNlq or window.NlqInit', () => {
        const hasImport = appJs.includes('import { initNlq }');
        const hasWindowInit = appJs.includes('window.NlqInit') || appJs.includes('NlqInit');
        expect(hasImport || hasWindowInit).toBe(true);
        // Accept any of: NlqInit(, initNlq(, or nlqInit( (local alias)
        const callsInit = appJs.includes('NlqInit(') || appJs.includes('initNlq(') || appJs.includes('nlqInit(');
        expect(callsInit).toBe(true);
    });
});
