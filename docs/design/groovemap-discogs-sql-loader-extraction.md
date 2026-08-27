# GrooveMap Discogs SQL loader extraction evidence

## Destination and history

- Destination: `groovemap-music/discogs-sql-loader` (private)
- Local preparation: `/Users/Robert/workspaces/github/groovemap/discogs-sql-loader`
- Source ref: `wt/bead/issue/discogsography-2kpm.15` at `e3e461be`
- Extraction: disposable `--no-local` clone followed by `git filter-repo`
- History: 198 source revisions retained on `main`, followed by establishment commit
  `44c0969` and recovery-evidence commit `5f525e1`; no tags migrated
- Exact paths and path rewrites are recorded in the destination's `docs/extraction.md`

The extraction retained `tableinator/`, its owned tests, its Docker build unit, applicable
PostgreSQL, resilience, completion, performance, and query-optimization documents, and
license history. Tests were promoted from `tests/tableinator/` to `tests/`.

## Standalone boundary

- Root PEP 621 package: `groovemap-discogs-sql-loader` at version `0.1.0`
- Runtime dependency: `groovemap-runtime`, pinned to immutable `python-libraries` commit
  `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`
- Catalog-event contract and generated Python binding: v1 from immutable
  `catalog-ingestion` commit `e7038d1492da54e91444bfa990598e8963972ce2`
- Persistence contract: v1 from immutable `database-schema` commit
  `4622bfeb4cd9c9553cbf640bb96c1e80b2cba710`
- Monorepo-wide configuration, sample-data, database, global-state, and outage fixtures
  needed by this service were reduced to service-owned fixtures in the destination
- `uv.lock`, pinned mise tools, `Justfile`, source-only CI, Commitizen, release dry run,
  install check, and a pinned container build are present
- The service image runs as UID:GID `1000:1000`

## Verification

Executed in the destination repository:

- `just check`: passed
  - Ruff format/lint passed
  - mypy passed for five source files
  - 184 tests passed with 96% total coverage
  - wheel and sdist built
  - fresh wheel install/import check passed
  - MIT and third-party license checks passed
  - Commitizen dry-run calculated `0.2.0` without changing the tree
- `just audit`: no known vulnerabilities; unpublished first-party packages were reported
  as unauditable by PyPI name as expected
- `just release-dry-run`: generated checksums, CycloneDX SBOM, third-party notices, and
  provenance without tagging, pushing, publishing, or releasing
- `just image`: pinned image built, imported successfully, and verified UID:GID
  `1000:1000`
- `gitleaks git --redact --no-banner`: clean across all filtered refs
- `gitleaks dir . --redact --no-banner`: clean current tree

The prepared `main` branch was pushed explicitly to the previously empty private
repository. Source CI run `33109318300` passed for destination commit `5f525e1`. No
image, package, tag, release, or public visibility change was created.

## Source recovery verification

An initial command-context error invoked `git filter-repo` in the local source clone. No
source remote was changed. The filter's ref map supplied every exact pre-filter branch
object ID; missing objects were recovered from an intact pre-filter clone or GitHub. All
47 branch tips matched the recorded pre-filter IDs, every linked Beadhive worktree was
clean, `git fsck --full --no-dangling` passed, `bh hive ready` passed, and source `main`
matched unchanged public commit `204f49e`. The accidental filtered refs remain under
`refs/backup/filter-repo-20260827/`, the intact recovery clone remains under
`groovemap/.recovery/`, and the original monorepo working tree is clean.
