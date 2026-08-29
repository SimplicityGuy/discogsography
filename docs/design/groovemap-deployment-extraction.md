# GrooveMap deployment extraction evidence

The private `groovemap-music/deployment` repository was extracted without
deleting or changing source content in this monorepo.

## History and safety

An isolated `--no-local --single-branch --no-tags` clone of
`wt/bead/issue/discogsography-2kpm.23` was filtered with the exact command
recorded in the destination's `docs/extraction.md`. The selected paths cover
Compose, production secret examples/bootstrap and entrypoints, deployment/API
performance tests, and stack-level operations documentation.

The filtered branch retained 288 source commits. Standalone establishment commit
`690c99714e29b1f1c9103ac5901956cd71fa3971` established the destination. A second
path-filtered history import retained five revisions of the three root data-maintenance
scripts before the reviewed, safe implementations were overlaid. The destination now
contains 297 commits at `5b997c1f7aa94d29a753de1903e5bd7e2fe796e8`. Current code remains PolyForm
Noncommercial 1.0.0; earlier license states remain visible in retained history.

During local preparation, one filter command was initially invoked from the
source clone instead of the isolated clone. It was caught before any push. The
source object graph was restored from the untouched standalone snapshot, every
AGF worktree was reset to its pre-filter full-tree commit and verified clean,
and source `main` was verified byte-for-byte against GitHub commit
`204f49e2429f074546dfc67e6354be2529a983ac`. No source remote ref or GitHub
history changed.

## Repository boundaries

- All sibling service build contexts were removed. Eleven internal services
  require digest-pinned image inputs owned by their source repositories.
- RabbitMQ, PostgreSQL, Neo4j, Redis, and the Dockerfile frontend are pinned to
  registry manifest digests.
- `catalog-api/performance/` owns the API performance runner, its Dockerfile, and its
  locked Python dependencies. Deployment owns only the environment-specific
  `tests/perftest/config.yaml` and a wrapper that requires an immutable
  `PERFTEST_IMAGE@sha256` input, eliminating the earlier duplicate implementation.
- The extraction rules are promoted from `catalog-ingestion` commit
  `e7038d1492da54e91444bfa990598e8963972ce2` with source and promoted SHA-256
  provenance; Compose no longer mounts a sibling source path.
- Runtime `.env`, `secrets/`, Docker authentication, stateful volumes, and
  performance results remain untracked. No PAT or plaintext production secret
  was introduced.
- Three retained Neo4j maintenance scripts default to read-only/dry-run behavior,
  require explicit `--apply` for mutation, accept `NEO4J_PASSWORD_FILE`, and never put
  secret values in Docker arguments or logs.
- This repository is intentionally unversioned because source repositories own
  versioned images; an environment is identified by its complete image digest
  set.

## Verification

- `just check`: formatting/lint, image ownership/digest policy, dependency licenses,
  base/production/smoke Compose merges, history/current-tree secret scans, and 60
  deployment tests passed. The tests include migration-script dry-run/apply behavior,
  secret-file handling, and the performance ownership boundary.
- `just build`: Compose configuration validation passed. Building or running the API
  performance image belongs to `catalog-api`; running a selected digest against an
  environment is an explicit deployment operation.
- `just smoke-infra`: clean RabbitMQ, PostgreSQL, Neo4j, and Redis instances all
  reached healthy state from their pinned digests with no host ports exposed;
  the temporary containers, volumes, and network were then removed.
- A full application-stack smoke remains deliberately pending until approved
  source repositories publish images and their exact digests are selected. No
  image was published as part of this migration.

The destination repository is private and `main` points to the current history merge.
Credential-free destination Source CI run `33122083884` passed.
