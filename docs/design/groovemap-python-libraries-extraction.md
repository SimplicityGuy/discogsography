# `groovemap-music/python-libraries` extraction evidence

Date: 2026-08-27

Destination: <https://github.com/groovemap-music/python-libraries>

Visibility: private

## History

The extraction used a new local clone of `SimplicityGuy/discogsography` at source head
`204f49e2429f074546dfc67e6354be2529a983ac`. `git filter-repo` selected only `main` and
retained `common/`, `tests/common/`, `tests/test_health_server.py`, and `LICENSE`, promoting
the shared source and tests to the destination root. The exact commands are committed in
the destination's `docs/extraction.md`.

The filter retained 154 relevant commits. One destination migration commit
(`28fa329702bc76896cc54ab8d05ec5b1bd3d929e`) established the standalone current tree, for
155 commits total. No tags were copied or created. The original monorepo remains clean at
the same source head.

## Current repository contract

- `groovemap-runtime` and `groovemap-agent-tools` are separate wheels in one uv workspace;
- both packages are version `0.1.0`, MIT licensed, typed, and synchronized by Commitizen;
- service configuration, OAuth, and extraction state are excluded from the current shared
  boundary while their historical shared revisions remain recoverable;
- Python 3.14.5, uv 0.12.5, just 1.57.0, and gitleaks 8.30.1 are pinned;
- the uv lockfile and both package license files are committed;
- CI and release-build dependencies use immutable action SHAs;
- the release workflow builds checksums and a CycloneDX SBOM but does not publish a
  package, tag, or GitHub Release.

## Verification

- `just check`: passed;
- unit tests: 406 passed, 2 live-RabbitMQ integration tests deselected;
- mypy: 12 source files checked with no issues;
- Ruff format and lint: passed;
- both sdists and wheels built successfully;
- isolated wheel installation and imports: passed;
- first-party metadata and dependency-license gate: passed;
- `pip-audit`: no known third-party vulnerabilities; the two unpublished first-party
  packages were correctly reported as unavailable on PyPI;
- gitleaks history scan: 149 destination commits scanned, no leaks;
- gitleaks current-tree scan: no leaks;
- Commitizen dry run: `0.1.0` to `0.2.0`, with no files modified;
- release dry run: checksums and CycloneDX SBOM generated locally, nothing published;
- GitHub Actions CI run `33043121725`: passed at the pushed extraction commit;
- remote default branch: `main`; remote visibility: private; local working tree: clean;
- remote tags: none.

The private-package consumer design intentionally avoids cross-repository PATs. A narrowly
installed GitHub App remains required before private Git dependencies are consumed in CI or
container builds.
