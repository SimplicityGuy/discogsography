import { access } from 'node:fs/promises';
import path from 'node:path';

export const canonicalOrigin = 'https://groovemap.music';

export function normalizeInternalReference(
  reference,
  documentUrl = `${canonicalOrigin}/`,
) {
  if (
    !reference ||
    reference.startsWith('mailto:') ||
    reference.startsWith('tel:') ||
    reference.startsWith('data:')
  ) {
    return null;
  }

  if (reference.startsWith('#')) {
    const url = new URL(documentUrl);
    url.hash = reference;
    return url;
  }

  const url = new URL(reference, documentUrl);
  if (url.origin !== canonicalOrigin) {
    return null;
  }

  return url;
}

export function outputPathForUrl(outputRoot, url) {
  const pathname = decodeURIComponent(url.pathname);
  if (pathname.endsWith('/')) {
    return path.join(outputRoot, pathname, 'index.html');
  }

  return path.join(outputRoot, pathname);
}

export async function assertReferenceExists(outputRoot, url) {
  await access(outputPathForUrl(outputRoot, url));
}

export function referencesFromHtml(html) {
  const references = [];
  const attributePattern = /\b(?:href|src)=(?:"([^"]+)"|'([^']+)')/gu;
  for (const match of html.matchAll(attributePattern)) {
    references.push(match[1] ?? match[2]);
  }
  return references;
}

export function idsFromHtml(html) {
  const ids = new Set();
  const idPattern = /\bid=(?:"([^"]+)"|'([^']+)')/gu;
  for (const match of html.matchAll(idPattern)) {
    ids.add(match[1] ?? match[2]);
  }
  return ids;
}
