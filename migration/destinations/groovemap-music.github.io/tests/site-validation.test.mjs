import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  canonicalOrigin,
  idsFromHtml,
  normalizeInternalReference,
  outputPathForUrl,
  referencesFromHtml,
} from '../scripts/site-validation.mjs';

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
);

test('normalizes only same-origin site references', () => {
  assert.equal(
    normalizeInternalReference('/about/', `${canonicalOrigin}/`).href,
    `${canonicalOrigin}/about/`,
  );
  assert.equal(
    normalizeInternalReference('#details', `${canonicalOrigin}/about/`).href,
    `${canonicalOrigin}/about/#details`,
  );
  assert.equal(
    normalizeInternalReference('https://github.com/groovemap-music'),
    null,
  );
  assert.equal(normalizeInternalReference('mailto:test@example.com'), null);
});

test('maps routes and assets to generated output paths', () => {
  assert.equal(
    outputPathForUrl('/tmp/dist', new URL('/', canonicalOrigin)),
    '/tmp/dist/index.html',
  );
  assert.equal(
    outputPathForUrl('/tmp/dist', new URL('/about/', canonicalOrigin)),
    '/tmp/dist/about/index.html',
  );
  assert.equal(
    outputPathForUrl(
      '/tmp/dist',
      new URL('/brand/favicon.svg', canonicalOrigin),
    ),
    '/tmp/dist/brand/favicon.svg',
  );
});

test('extracts references and fragment identifiers from HTML', () => {
  const html =
    '<main id="content"><a href="#content"><img src="/brand/favicon.svg" alt=""></a></main>';
  assert.deepEqual(referencesFromHtml(html), [
    '#content',
    '/brand/favicon.svg',
  ]);
  assert.deepEqual([...idsFromHtml(html)], ['content']);
});

test('keeps the Astro root-site and disabled deployment contracts', async () => {
  const astroConfig = await readFile(
    path.join(repositoryRoot, 'astro.config.mjs'),
    'utf8',
  );
  assert.match(astroConfig, /site: 'https:\/\/groovemap\.music'/u);
  assert.doesNotMatch(astroConfig, /\bbase\s*:/u);

  const pagesWorkflow = await readFile(
    path.join(repositoryRoot, '.github', 'workflows', 'pages.yml.disabled'),
    'utf8',
  );
  assert.match(pagesWorkflow, /contents: read/u);
  assert.match(pagesWorkflow, /pages: write/u);
  assert.match(pagesWorkflow, /id-token: write/u);
  assert.match(pagesWorkflow, /environment:\n\s+name: github-pages/u);
  assert.match(pagesWorkflow, /uses: [^@]+@[0-9a-f]{40}/u);
});

test('declares an unversioned private package with no publication hooks', async () => {
  const manifest = JSON.parse(
    await readFile(path.join(repositoryRoot, 'package.json'), 'utf8'),
  );
  assert.equal(manifest.private, true);
  assert.equal(manifest.version, '0.0.0-private');
  assert.equal(manifest.packageManager, 'npm@12.0.2');
  assert.equal(manifest.scripts.release, undefined);
  assert.equal(manifest.devDependencies?.commitizen, undefined);
});
