# GrooveMap Discogs graph enricher extraction evidence

## Destination and history

- Destination: `groovemap-music/discogs-graph-enricher` (private)
- Local preparation: `/Users/Robert/workspaces/github/groovemap/discogs-graph-enricher`
- Source ref: `wt/bead/issue/discogsography-2kpm.14` at `e4274316`
- Extraction: disposable `--no-local` clone followed by `git filter-repo`; the original
  monorepo and refs were not modified
- History: 220 source revisions retained on `main`, followed by establishment commit
  `96f6665`; no tags migrated
- Exact paths and path rewrites are recorded in the destination's `docs/extraction.md`

The extraction retained `graphinator/`, its owned tests, its Docker build unit, applicable
graph, resilience, indexing, and profiling documents, and license history. Tests were
promoted from `tests/graphinator/` to `tests/`.

## Standalone boundary

- Root PEP 621 package: `groovemap-discogs-graph-enricher` at version `0.1.0`
- Runtime dependency: `groovemap-runtime`, pinned to immutable `python-libraries` commit
  `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`
- Catalog-event contract and generated Python binding: v1 from immutable
  `catalog-ingestion` commit `e7038d1492da54e91444bfa990598e8963972ce2`
- Persistence contract: v1 from immutable `database-schema` commit
  `4622bfeb4cd9c9553cbf640bb96c1e80b2cba710`
- Monorepo-wide test fixtures needed by this service were reduced to service-owned
  fixtures in the destination, removing the hidden root `tests/conftest.py` dependency
- `uv.lock`, pinned mise tools, `Justfile`, source-only CI, Commitizen, release dry run,
  install check, and a pinned container build are present
- The service image runs as UID:GID `1000:1000`

## Verification

Executed in the destination repository:

- `just check`: passed
  - Ruff format/lint passed
  - mypy passed for five source files
  - 283 tests passed with 95% total coverage
  - wheel and sdist built
  - fresh wheel install/import check passed
  - MIT and third-party license checks passed
  - Commitizen dry-run calculated `0.2.0` without changing the tree
- `just audit`: no known vulnerabilities; the unpublished first-party runtime package was
  reported as unauditable by PyPI name as expected
- `just release-dry-run`: generated checksums, CycloneDX SBOM, third-party notices, and
  provenance without tagging, pushing, publishing, or releasing
- `just image`: pinned image built, imported successfully, and verified UID:GID
  `1000:1000`
- `gitleaks git --redact --no-banner`: clean across all filtered refs
- `gitleaks dir . --redact --no-banner`: clean current tree

The prepared `main` branch was pushed explicitly to the previously empty private
repository. Source CI run `33107911678` passed for destination commit `96f6665`. No
image, package, tag, release, or public visibility change was created.
