# GrooveMap deployment extraction evidence

The private `groovemap-music/deployment` repository was extracted without
deleting or changing source content in this monorepo.

## History and safety

An isolated `--no-local --single-branch --no-tags` clone of
`wt/bead/issue/discogsography-2kpm.23` was filtered with the exact command
recorded in the destination's `docs/extraction.md`. The selected paths cover
Compose, production secret examples/bootstrap and entrypoints, deployment/API
performance tests, and stack-level operations documentation.

The filtered branch retained 288 source commits. Standalone establishment
commit `690c99714e29b1f1c9103ac5901956cd71fa3971` produces 289 destination
commits. Current code remains PolyForm Noncommercial 1.0.0; earlier license
states remain visible in retained history.

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
- RabbitMQ, PostgreSQL, Neo4j, Redis, the performance-test Python base, and the
  Dockerfile frontend are pinned to registry manifest digests.
- The API performance-test Python dependencies are version/hash locked and
  have a complete reviewed license manifest.
- The extraction rules are promoted from `catalog-ingestion` commit
  `e7038d1492da54e91444bfa990598e8963972ce2` with source and promoted SHA-256
  provenance; Compose no longer mounts a sibling source path.
- Runtime `.env`, `secrets/`, Docker authentication, stateful volumes, and
  performance results remain untracked. No PAT or plaintext production secret
  was introduced.
- This repository is intentionally unversioned because source repositories own
  versioned images; an environment is identified by its complete image digest
  set.

## Verification

- `just check`: formatting/lint, image ownership/digest policy, dependency
  licenses, base/production/smoke Compose merges, history/current-tree secret
  scans, and 49 deployment tests passed.
- `just build`: the locked API performance-test image built successfully and
  ran as user `perftest`; its runtime imports and embedded license manifest
  were verified without publishing.
- `just smoke-infra`: clean RabbitMQ, PostgreSQL, Neo4j, and Redis instances all
  reached healthy state from their pinned digests with no host ports exposed;
  the temporary containers, volumes, and network were then removed.
- A full application-stack smoke remains deliberately pending until approved
  source repositories publish images and their exact digests are selected. No
  image was published as part of this migration.

The destination repository is private and `main` points to the establishment
commit. Credential-free destination Source CI run `33118868242` passed.
