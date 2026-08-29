# GrooveMap analytics engine extraction evidence

## Destination and history

- Destination: `groovemap-music/analytics-engine` (private)
- Local preparation: `/Users/Robert/workspaces/github/groovemap/analytics-engine`
- Source ref: `wt/bead/issue/discogsography-2kpm.19` at `8d5ec8cf`
- Extraction: disposable `--no-local` clone followed by `git filter-repo`; the original
  monorepo and refs were not modified
- History: 103 source revisions retained on `main`, followed by establishment commit
  `adddf41`; no tags migrated
- Exact paths and path rewrites are recorded in the destination's `docs/extraction.md`

The extraction retained `insights/`, its service-owned tests, the PolyForm license, and
applicable resilience, indexing, performance, query-optimization, and rarity design
documents. Tests were promoted from `tests/insights/` to `tests/`. Query implementation
tests that import API source were assigned to `catalog-api` instead of preserving a false
cross-repository test dependency.

## Standalone boundary

- Root PEP 621 package: `groovemap-analytics-engine` at version `0.1.0`
- Runtime dependency: `groovemap-runtime`, pinned to immutable `python-libraries` commit
  `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`
- Internal Insights OpenAPI contract and generated Python binding: v1 from immutable
  `catalog-api` commit `8b6858dcfe69cd011d430856e553eb9c8459fd90`
- The producer contract publishes the community-enrichment processing budget; the
  analytics read timeout derives from that promoted value rather than importing API code
- The API-owned Neo4j query tests moved to `catalog-api`, whose updated 1,918-test gate
  and Source CI run `33110091964` passed
- `uv.lock`, pinned mise tools, `Justfile`, source-only CI, Commitizen, release dry run,
  install check, and a pinned container build are present
- The service image runs as UID:GID `1000:1000`

## Verification

Executed in the destination repository:

- `just check`: passed
  - Ruff format/lint passed
  - mypy passed for seven source files
  - 147 tests passed with 96% total coverage
  - wheel and sdist built
  - fresh wheel install/import check passed
  - PolyForm and third-party license checks passed
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
repository. Source CI run `33110833548` passed for destination commit `adddf41`. No
image, package, tag, release, or public visibility change was created. A hosted release
workflow remains disabled until a short-lived GitHub App identity can read the private
runtime repository and an approved publishing identity exists.
