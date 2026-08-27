# GrooveMap catalog API extraction evidence

## Destination and history

- Destination: `groovemap-music/catalog-api` (private)
- Local preparation: `/Users/Robert/workspaces/github/groovemap/catalog-api`
- Source ref: `wt/bead/issue/discogsography-2kpm.13` at `006cc064`
- Extraction: disposable `--no-local` clone followed by `git filter-repo`; the original
  monorepo and refs were not modified
- History: 259 source revisions retained on `main`, followed by establishment commit
  `983bc29`; no tags migrated
- Exact paths and path rewrites are recorded in the destination's `docs/extraction.md`

The extraction retained `api/`, API tests, the API performance runner, applicable design
and operational documents, and the PolyForm license. Tests were promoted from
`tests/api/` to `tests/`; the performance runner was promoted from `tests/perftest/` to
`performance/`.

## Standalone boundary

- Root PEP 621 package: `groovemap-catalog-api` at version `0.1.0`
- Private dependencies: `groovemap-runtime` and `groovemap-agent-tools`, both pinned to
  immutable `python-libraries` commit `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`
- Persistence contract: v1 from immutable `database-schema` commit
  `4622bfeb4cd9c9553cbf640bb96c1e80b2cba710`
- Catalog-event contract: v1 from immutable `catalog-ingestion` commit
  `e7038d1492da54e91444bfa990598e8963972ce2`
- Internal Analytics OpenAPI and generated Python binding remain API-owned; generation no
  longer writes into a sibling repository
- `uv.lock`, pinned mise tools, `Justfile`, source-only CI, Commitizen, release dry run,
  install check, and two pinned container build units are present
- The service image runs as UID:GID `1000:1000`; the performance image uses a dedicated
  unprivileged account

## Verification

Executed from a clean dependency environment in the destination repository:

- `just check`: passed
  - Ruff format/lint passed
  - mypy passed for 75 source files
  - 1,910 tests passed with 98% total coverage
  - wheel and sdist built
  - fresh wheel install/import check passed
  - PolyForm and third-party license checks passed
  - Commitizen dry-run calculated `0.2.0` without changing the tree
- `just audit`: no known vulnerabilities; unpublished first-party packages were reported
  as unauditable by PyPI name as expected
- `just release-dry-run`: generated checksums, CycloneDX SBOM, third-party notices, and
  provenance without tagging, pushing, publishing, or releasing
- `just image`: pinned service image built, imported successfully, and verified
  UID:GID `1000:1000`
- `just performance-image`: pinned performance runner image built successfully
- `gitleaks git --redact --no-banner`: clean across all filtered refs
- `gitleaks dir . --redact --no-banner`: clean current tree

Three generic scanner matches were classified as non-secret test/document fixtures and
covered by exact path-and-line-shape allowlist rules. No matched value is reproduced here.

The prepared `main` branch was pushed explicitly to the previously empty private
repository. Source CI run `33106985327` passed for destination commit `983bc29`. No
image, package, tag, release, or public visibility change was created.
