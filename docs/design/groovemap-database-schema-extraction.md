# `groovemap-music/database-schema` extraction evidence

Date: 2026-08-27

Destination: <https://github.com/groovemap-music/database-schema>

Visibility: private

## Boundary and history

The extraction used a new clone of `SimplicityGuy/discogsography` at source head
`204f49e2429f074546dfc67e6354be2529a983ac`. `git filter-repo` selected only `main` and
retained `schema-init/`, `tests/schema-init/`, and `LICENSE`, promoting owned source and
tests to the destination root. Exact commands are committed in `docs/extraction.md`.

The filter retained 79 relevant commits. Destination commit
`4622bfeb4cd9c9553cbf640bb96c1e80b2cba710` established the independent compatibility
authority. The later, approved MIT conversion produced current commit
`6a29e2859a2177eebae1d97dd8550997ff43e9d0`, for 81 commits total. No source tags were
present or copied.

The current repository owns Neo4j/PostgreSQL definitions and versioned compatibility
metadata. The historical one-shot runner, Dockerfile, and orchestration test are excluded
from the current tree because credentials, live application, and rollback orchestration
belong to `deployment`; their earlier revisions remain recoverable in filtered history.

## Repository contract

- `groovemap-database-schema` version `0.1.0` is a typed PEP 621 package;
- current source is MIT licensed as approved; retained historical revisions preserve
  their then-applicable PolyForm Noncommercial 1.0.0 terms and notice;
- runtime compatibility names `groovemap-runtime` version `0.1.0` and immutable commit
  `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`;
- the optional private runtime dependency is not required by the credential-free default
  gate and remained unfetched in GitHub Actions;
- the wheel contains both schema modules and `contracts/persistence/v1/compatibility.json`;
- Commitizen owns annotated `v$version` release versioning;
- the release workflow builds checksums and a CycloneDX SBOM without publishing.

## Verification

- `just check`: passed without database credentials or connections;
- 60 Neo4j/PostgreSQL definition tests: passed;
- Ruff and mypy: passed;
- compatibility-policy validation: passed;
- sdist, wheel, isolated install/import, and embedded-contract checks: passed;
- license enumeration: passed;
- `pip-audit`: no known third-party vulnerabilities; the unpublished first-party package
  was correctly unavailable on PyPI;
- gitleaks history scan: 81 commits scanned, no leaks;
- gitleaks current-tree scan: no leaks;
- Commitizen dry run: `0.1.0` to `0.2.0`, no files modified;
- release dry run: checksums and CycloneDX SBOM generated locally, nothing published;
- GitHub Actions CI run `33120062891`: passed at the current MIT-licensed head;
- remote branch: clean `main`; visibility: private; remote tags: none;
- the original monorepo remains clean and unchanged.
