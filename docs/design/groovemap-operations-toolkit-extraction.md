# `groovemap-music/operations-toolkit` extraction evidence

Date: 2026-08-27

Destination: <https://github.com/groovemap-music/operations-toolkit>

Visibility: private

## Boundary and history

The extraction used a disposable clone of the migration branch
`wt/bead/issue/discogsography-2kpm.18` at
`dd6f5d693d8a16a486894687356768bb91c7514f`. `git filter-repo` retained
`utilities/`, `tests/utilities/`, and the root license, promoting the owned tests to
`tests/`. The exact command is committed in the destination's `docs/extraction.md`.

The filter retained 35 relevant commits. Destination commit
`15be6ff42338d0895ef2f4b6c55b661a6da2f0e8` established the independent package and
validation contract. The later, approved MIT conversion produced current commit
`2d25ee1151db6d6c0fe6d7f3b048bd1aeee1460e`, for 37 commits total. No tags were copied
or created. The original
monorepo `main` remains clean and unchanged at
`204f49e2429f074546dfc67e6354be2529a983ac`.

The current tree is MIT licensed as approved; historical revisions retain their
then-applicable license text.

## Repository contract

- one versioned Python wheel owns six observational operator CLIs;
- live commands do not purge queues, mutate databases, restart services, or print secret
  values;
- passwords use `<NAME>_FILE` before `<NAME>` and the behavior is repository-local and
  directly tested, removing the former monorepo-relative runtime import;
- the catalog-event contract and Python queue-name binding are byte-for-byte promoted from
  immutable `catalog-ingestion` commit
  `e7038d1492da54e91444bfa990598e8963972ce2` with SHA-256 drift checks;
- Python 3.14.5, uv 0.12.5, just 1.57.0, and gitleaks 8.30.1 are pinned;
- the uv lockfile and immutable GitHub Actions SHAs are committed;
- Commitizen reads the PEP 621 version and previews annotated `v$version` tags;
- the release workflow validates a candidate but does not publish packages, tags, or
  releases.

## Verification

- `just check`: passed;
- 76 focused tests: passed;
- Ruff format/lint and strict mypy over 9 source modules: passed;
- producer contract and generated binding digests: passed;
- sdist/wheel build and isolated wheel installation/import/CLI check: passed;
- current license and dependency-license policy: passed;
- gitleaks history scan: 37 commits scanned, no leaks;
- gitleaks current-tree scan: no leaks;
- `pip-audit`: no known third-party vulnerabilities; the unpublished first-party package
  was correctly unavailable on PyPI;
- Commitizen dry run: `0.1.0` to `0.2.0`, no files modified;
- release dry run: checksums, CycloneDX SBOM, third-party notices, and build metadata
  generated locally; nothing published;
- GitHub Actions CI run `33120062536`: passed at the current MIT-licensed head;
- remote default branch: `main`; remote visibility: private; remote tags: none;
- destination working tree: clean and synchronized with remote `main`.
