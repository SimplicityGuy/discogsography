import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
);
const lock = JSON.parse(
  await readFile(path.join(repositoryRoot, 'package-lock.json'), 'utf8'),
);
const allowedTokens = new Set([
  '0BSD',
  'Apache-2.0',
  'BlueOak-1.0.0',
  'BSD-2-Clause',
  'BSD-3-Clause',
  'CC0-1.0',
  'ISC',
  'MIT',
  'MPL-2.0',
  'Python-2.0',
  'Unlicense',
]);
const failures = [];
let inspectedPackages = 0;
const policy = JSON.parse(
  await readFile(
    path.join(repositoryRoot, 'docs', 'dependency-license-policy.json'),
    'utf8',
  ),
);
const exceptions = new Map(
  policy.exceptions.map((exception) => [
    `${exception.name}@${exception.version}`,
    exception,
  ]),
);

function packageNameFromLockPath(lockPath) {
  const marker = 'node_modules/';
  const start = lockPath.lastIndexOf(marker);
  return start === -1 ? null : lockPath.slice(start + marker.length);
}

function isGenerallyAllowed(expression) {
  const tokens = expression.match(/[A-Za-z0-9.-]+/gu) ?? [];
  const licenseTokens = tokens.filter(
    (token) => token !== 'AND' && token !== 'OR' && token !== 'WITH',
  );
  return (
    licenseTokens.length > 0 &&
    licenseTokens.every((token) => allowedTokens.has(token))
  );
}

function hasNarrowException(manifest, license) {
  const exception = exceptions.get(`${manifest.name}@${manifest.version}`);
  return exception?.license === license;
}

for (const lockPath of Object.keys(lock.packages)) {
  const packageName = packageNameFromLockPath(lockPath);
  if (!packageName) continue;

  try {
    const manifestPath = path.join(repositoryRoot, lockPath, 'package.json');
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    inspectedPackages += 1;
    const license =
      typeof manifest.license === 'string' ? manifest.license : null;
    if (
      !license ||
      (!isGenerallyAllowed(license) && !hasNarrowException(manifest, license))
    )
      failures.push(`${packageName}: ${license ?? 'missing license metadata'}`);
  } catch (error) {
    if (error.code !== 'ENOENT') {
      failures.push(
        `${packageName}: unreadable package manifest (${error.code ?? 'unknown error'})`,
      );
    }
  }
}

const rootFiles = new Set(await readdir(repositoryRoot));
if (!rootFiles.has('LICENSE'))
  failures.push('repository: missing first-party LICENSE');
if (!rootFiles.has('THIRD_PARTY_NOTICES.md'))
  failures.push('repository: missing THIRD_PARTY_NOTICES.md');

const notice = await readFile(
  path.join(repositoryRoot, 'THIRD_PARTY_NOTICES.md'),
  'utf8',
);
for (const exception of exceptions.values()) {
  if (
    !notice.includes(`${exception.name} ${exception.version}`) ||
    !notice.includes(exception.obligations.sourceUrl) ||
    !notice.includes(exception.obligations.licenseUrl)
  ) {
    failures.push(
      `${exception.name}@${exception.version}: notice does not record required source and license links`,
    );
  }

  if (exception.obligations.distributedInSite === false) {
    const distEntries = await readdir(path.join(repositoryRoot, 'dist'), {
      recursive: true,
    });
    const forbidden = distEntries.filter((entry) =>
      /(?:libvips|\.dylib$|\.node$)/u.test(entry),
    );
    if (forbidden.length > 0) {
      failures.push(
        `${exception.name}@${exception.version}: build unexpectedly distributes ${forbidden.join(', ')}`,
      );
    }
  }
}

if (failures.length > 0) {
  throw new Error(
    `Dependency license policy failed:\n- ${failures.sort().join('\n- ')}`,
  );
}

console.log(
  `Validated licenses for ${inspectedPackages} installed locked package paths.`,
);
