# GrooveMap graph explorer extraction evidence

## Destination and history

- Destination: `groovemap-music/graph-explorer` (private)
- Local preparation: `/Users/Robert/workspaces/github/groovemap/graph-explorer`
- Source ref: `wt/bead/issue/discogsography-2kpm.21` at `42b337a2`
- Extraction: disposable `--no-local` clone followed by `git filter-repo`; the original monorepo and refs were not modified
- History: 212 source revisions retained on `main`, followed by establishment commit `e9a4dbf`; no tags migrated
- Exact path selection and rewrites are recorded in the destination's `docs/extraction.md`

The extraction retained `explore/`, its JavaScript and browser-owned tests, directly relevant design records, and the PolyForm license. Four Python suites physically grouped under `tests/explore/` tested Catalog API implementations; equivalent consolidated coverage already lives in `catalog-api`, so those duplicates were excluded. An administrator-toast regression suite stored under Explore was transferred to its actual owner, `operations-console`, where three Vitest cases and Source CI run `33114163229` pass.

## Standalone boundary

- Root PEP 621 package: `groovemap-graph-explorer` at version `0.1.0`
- Runtime dependency: `groovemap-runtime`, pinned to immutable `python-libraries` commit `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`
- Catalog API method/path contract: v1 from immutable producer commit `100e9e84582cd24d0b4123b9861f1155ae729af7`; producer Source CI run `33113609712` passed
- Consumer validation checks the promoted contract digest and all `/api/*` browser route references; no Catalog API source import or sibling build context remains
- npm `11.19.0`, Node `26.7.0`, Tailwind CLI `4.3.3`, Tailwind forms `0.5.11`, Vitest `4.1.11`, browser libraries, fonts, and material symbols are exact and lockfile-pinned
- Browser dependencies are promoted into generated static build output, eliminating runtime and E2E dependence on external CDNs
- Canonical editable branding remains in `infra/brand` at immutable commit `342ee0d4d8a7290e55dfe1ad0d8fe82425ea2658`; promoted SVG/CSS/manifest digests are committed
- `uv.lock`, pinned mise tools, `Justfile`, source-only CI, Commitizen, release dry run, install check, and digest-pinned multi-stage container build are present

## Verification

Executed in the destination repository:

- `just check`: passed
  - Ruff, mypy, contract, brand, and current/history secret checks passed
  - six Python proxy tests passed; 1,143 Vitest cases passed
  - locked static assets, wheel, and source distribution built; generated CSS, browser libraries, and fonts are present in the wheel
  - fresh wheel install/import, first-party PolyForm, third-party license, and Commitizen `0.2.0` dry-run checks passed
- `just e2e`: 88 Chromium end-to-end tests passed against a consumer-owned mock Catalog API
- `just audit`: no known Python or npm vulnerabilities; unpublished first-party packages were reported as unauditable by PyPI name as expected
- `just release-dry-run`: generated checksums, CycloneDX SBOM, third-party notices, and provenance without publishing
- `just image`: digest-pinned image built, imported successfully, and verified UID:GID `1000:1000`; `.dockerignore` limits build context to 1.41 MB
- history and current-tree gitleaks scans passed; deterministic brand digests use an exact path-and-line-shape allowlist

The prepared `main` branch was pushed explicitly to the previously empty private repository at commit `e9a4dbf1d5faec10e3f29844a87be646911d5966`. Source CI run `33116042283` was dispatched for that commit. No image, package, tag, release, or public visibility change was created. Hosted release automation remains disabled pending approved private-dependency and publishing identities.
