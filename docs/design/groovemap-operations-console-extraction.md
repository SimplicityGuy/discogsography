# GrooveMap operations console extraction evidence

## Destination and history

- Destination: `groovemap-music/operations-console` (private)
- Local preparation: `/Users/Robert/workspaces/github/groovemap/operations-console`
- Source ref: `wt/bead/issue/discogsography-2kpm.20` at `4ebbcb8b`
- Extraction: disposable `--no-local` clone followed by `git filter-repo`; the original
  monorepo and refs were not modified
- History: 194 source revisions retained on `main`, followed by establishment commit
  `3f0d3cc`; no tags migrated
- Exact ownership and path rewrites are recorded in the destination's
  `docs/extraction.md`

The extraction retained `dashboard/`, its Python and browser-owned tests, the PolyForm
license, the administrator guide, and dashboard-specific design records. Tests were
promoted from `tests/dashboard/` to `tests/`. Platform-wide monitoring documentation is
reserved for `deployment`; Explore browser tests remain with `graph-explorer`.

## Standalone boundary

- Root PEP 621 package: `groovemap-operations-console` at version `0.1.0`
- Runtime dependency: `groovemap-runtime`, pinned to immutable `python-libraries` commit
  `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`
- Catalog-event queue contract and generated binding: v1 from immutable
  `catalog-ingestion` commit `e7038d1492da54e91444bfa990598e8963972ce2`
- Persistence compatibility contract: v1 from immutable `database-schema` commit
  `4622bfeb4cd9c9553cbf640bb96c1e80b2cba710`
- Admin proxy route contract and generated binding: v1 from immutable `catalog-api`
  commit `6d91a4cdb60b9ea34946878e4a578a4c98370e6f`; producer Source CI run
  `33112090834` passed after 1,919 API tests passed locally
- Tailwind CLI `4.3.3` and forms plugin `0.5.11` are exact and committed in an npm
  lockfile; the Docker CSS stage uses a digest-pinned Node `26.7.0` image
- Canonical editable branding remains in `infra/brand` at immutable commit
  `342ee0d4d8a7290e55dfe1ad0d8fe82425ea2658`; promoted SVG/CSS/manifest digests and
  a deterministic promotion/check script are committed
- `uv.lock`, pinned mise tools, `Justfile`, source-only CI, Commitizen, release dry run,
  install check, and a pinned multi-stage container build are present

## Verification

Executed in the destination repository:

- `just check`: passed
  - Ruff format/lint and mypy passed for eight source files
  - 205 non-browser tests passed with 97% total coverage
  - locked Tailwind CSS, wheel, and sdist built; CSS and brand assets are in the wheel
  - fresh wheel install/import check passed
  - PolyForm and third-party license checks passed
  - Commitizen dry-run calculated `0.2.0` without changing the tree
- `just e2e`: eight Chromium end-to-end tests passed
- `just brand-promote`: all 12 deterministic assets matched the clean pinned infra source
- `just audit`: no known Python or npm vulnerabilities; unpublished first-party
  packages were reported as unauditable by PyPI name as expected
- `just release-dry-run`: generated checksums, CycloneDX SBOM, third-party notices, and
  provenance without tagging, pushing, publishing, or releasing
- `just image`: digest-pinned image built, imported successfully, and verified UID:GID
  `1000:1000`
- history and current-tree gitleaks scans passed; one deterministic asset-digest pattern
  is covered by an exact path-and-line-shape allowlist

The prepared `main` branch was pushed explicitly to the previously empty private
repository. Source CI run `33112684088` passed for destination commit `3f0d3cc`. No
image, package, tag, release, or public visibility change was created. Hosted release
automation remains disabled pending an approved short-lived private-dependency and
publishing identity design.
