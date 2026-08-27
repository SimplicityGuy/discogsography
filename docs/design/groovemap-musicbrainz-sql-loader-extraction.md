# `groovemap-music/musicbrainz-sql-loader` extraction evidence

Date: 2026-08-27

Destination: <https://github.com/groovemap-music/musicbrainz-sql-loader>

Visibility: private

Status: locally verified and private source CI green; full GitHub-hosted dependency/test
CI is approval-gated on the organization GitHub App design described below.

## Boundary and history

The extraction used a disposable clone of migration branch
`wt/bead/issue/discogsography-2kpm.17` at
`69d90758ddae646f8a54eb458f95ea340d144858`. `git filter-repo` retained
`brainztableinator/`, its owned tests, applicable MusicBrainz/PostgreSQL/resilience design
documents, and the license. Exact arguments are committed in the destination's
`docs/extraction.md`.

The filter retained 73 relevant commits. Destination commit
`4ca10ab1ac1b81d977017d31829db179a4244ae5` established the standalone repository, for
74 commits total. No tags were copied or created. The original monorepo `main` remains
clean and unchanged at `204f49e2429f074546dfc67e6354be2529a983ac`.

The current tree is MIT licensed by owner decision. Historical revisions retain their
then-applicable license text.

## Repository contract

- one service wheel and non-root container image own complete MusicBrainz-to-PostgreSQL loading;
- `groovemap-runtime[postgres,rabbitmq]` version `0.1.0` is pinned to immutable private
  `python-libraries` commit `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`;
- the catalog-event v1 contract and generated binding are promoted byte-for-byte from
  `catalog-ingestion` commit `e7038d1492da54e91444bfa990598e8963972ce2`;
- persistence compatibility v1 is promoted byte-for-byte from `database-schema` commit
  `4622bfeb4cd9c9553cbf640bb96c1e80b2cba710`;
- contract, binding, compatibility, and dependency-revision drift are SHA-256 checked;
- Python 3.14.5, uv 0.12.5, just 1.57.0, gitleaks 8.30.1, the Python lockfile, the
  Docker base digest, the Dockerfile frontend digest, and Actions SHAs are pinned;
- the container receives a locally built wheel from the verified runtime checkout, never
  a token or monorepo-relative source tree;
- Commitizen reads synchronized PEP 621/package versions and previews annotated
  `v$version` tags.

## Verification

- `just check`: passed;
- 126 focused mocked-service tests: passed with 95% total coverage;
- Ruff and strict mypy over four source modules: passed;
- exact catalog/persistence contracts and private runtime revision: passed;
- sdist/wheel build and isolated wheel/runtime installation: passed;
- current MIT and dependency-license checks: passed;
- `pip-audit`: no known third-party vulnerabilities; both unpublished first-party
  packages were correctly unavailable on PyPI;
- gitleaks history scan: 73 commits scanned, no leaks;
- gitleaks current-tree scan: no leaks;
- Commitizen dry run: `0.1.0` to `0.2.0`, no files modified;
- release dry run: checksums, CycloneDX SBOM, third-party notices, and build metadata
  generated locally; nothing published;
- digest-pinned container: built, imported the service, and ran as UID/GID 1000;
- GitHub Actions Source CI run `33105222419`: passed;
- remote default branch: `main`; visibility: private; tags: none; local tree: clean.

## Deliberate CI gate

GitHub's repository-scoped `GITHUB_TOKEN` cannot read the separate private
`python-libraries` repository. A stored cross-repository PAT is prohibited. Full hosted
installation, tests, image building, and release validation therefore remain disabled
until a narrowly installed GitHub App can mint a short-lived read token and its private-key,
state, and approval design is reviewed. The current automatic workflow performs only the
credential-free source/contract/secret gate and is green.
