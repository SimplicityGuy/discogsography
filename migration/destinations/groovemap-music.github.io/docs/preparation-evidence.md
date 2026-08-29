# Local preparation evidence

- Migration bead: `discogsography-2kpm.12`
- Destination: `groovemap-music/groovemap-music.github.io`
- Canonical site: `https://groovemap.music`
- Preparation location: `migration/destinations/groovemap-music.github.io`
- Source strategy: new static organization site; no monorepo site path exists to filter
- Version authority: none (unversioned Pages deployment)
- External changes during preparation: none
- Evidence captured: 2026-08-27 UTC

## Provenance and history

The Astro source is newly authored for this destination. It does not claim unrelated
monorepo commits as product-site history. Promoted brand assets come from the canonical
`groovemap-music/infra` renderer at the revision recorded in
`public/brand/provenance.json`; SHA-256 digests prove byte identity. The original
monorepo was not rewritten or cleaned.

## Local verification evidence

The following local gates passed without contacting a deployment target or exposing a
secret value:

```text
mise install                  PASS, Node 24.20.0 / npm 12.0.2 / just 1.57.0
just setup                    PASS, npm ci from package-lock.json
just check                    PASS
  Prettier                    PASS
  ESLint / Astro              PASS
  astro check                 PASS, 0 errors/warnings/hints
  node:test                   PASS, 5 tests
  astro build                 PASS, 3 static pages
  HTML/accessibility/links    PASS
  canonical metadata/assets  PASS
  brand SHA-256 provenance    PASS at infra 33fd6d2647612cf32a9f2e69689b9c432204148d
  dependency license policy  PASS, 363 installed locked package paths
Gitleaks directory scan       PASS, 0 findings, redacted output
TruffleHog filesystem scan   PASS, 0 findings (0 verified)
Commitizen configuration      ABSENT as required for an unversioned site
```

The installed macOS platform graph was inspected: Astro 7.2.8 optionally brings Sharp
0.35.4 and `@img/sharp-libvips-darwin-arm64` 1.3.3. The Ubuntu CI lock includes the
corresponding x64 package. Both exact LGPL exceptions, their build-only role, and their
notice/source obligations are recorded in `dependency-license-policy.json` and
`THIRD_PARTY_NOTICES.md`. The license gate confirms no libvips, dynamic library, or native
Node module is present in `dist`.

The in-app browser was unavailable during local preparation. Semantic HTML,
accessibility, responsive CSS, generated links, assets, and routes were validated
statically; the desktop/mobile visual pass remains an explicit activation check rather
than being represented as completed.

External repository existence, visibility, CI, Pages, DNS, HTTPS, and deployed-route
verification remain intentionally pending until their separate gates are approved.
