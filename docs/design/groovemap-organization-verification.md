# GrooveMap organization migration verification

Date: 2026-08-27

Organization: <https://github.com/groovemap-music>

Source: `SimplicityGuy/discogsography` at
`204f49e2429f074546dfc67e6354be2529a983ac`

This is the current evidence and approval-gate record for the private-first split. It
does not claim that public profile/Pages/DNS work is complete: those operations remain
deliberately unperformed pending explicit approval.

## Approved repository map and current evidence

Every repository below exists, is private, has default branch `main`, allows merge
commits and squash merges, disables rebase merges, and deletes merged branches. Each
listed CI run passed at the listed head. Local `main` and `origin/main` match and the
working tree is clean for every repository.

| Source boundary | Destination | Current / intended visibility | License | Commits | Current head | Passing CI |
| --- | --- | --- | --- | ---: | --- | ---: |
| New organization profile; source workflows distributed | `.github` | Private / public after review | MIT | 2 | `083f926` | `33120062732` |
| `insights/`, owned tests/docs | `analytics-engine` | Private / private | PolyForm Noncommercial 1.0.0 | 104 | `adddf41` | `33110833548` |
| `api/`, owned tests/docs, performance runner | `catalog-api` | Private / private | PolyForm Noncommercial 1.0.0 | 265 | `a51a6b6` | `33122498789` |
| `extractor/`, root Cargo workspace, owned tests/docs | `catalog-ingestion` | Private / private | MIT | 295 | `e7038d1` | `33045712279` |
| `schema-init/`, owned tests/docs | `database-schema` | Private / private | MIT | 81 | `6a29e28` | `33120062891` |
| Compose, secret examples, deployment tests/docs/scripts | `deployment` | Private / private | PolyForm Noncommercial 1.0.0 | 297 | `5b997c1` | `33122083884` |
| `graphinator/`, owned tests/docs | `discogs-graph-enricher` | Private / private | MIT | 222 | `d0e2a54` | `33122499267` |
| `tableinator/`, owned tests/docs | `discogs-sql-loader` | Private / private | MIT | 201 | `c5b5bee` | `33122499246` |
| `explore/`, owned Python/JS/E2E tests/docs | `graph-explorer` | Private / private | PolyForm Noncommercial 1.0.0 | 213 | `e9a4dbf` | `33116042283` |
| New Astro organization site | `groovemap-music.github.io` | Private / public after review | MIT | 2 | `933c1c7` | `33120062284` |
| Organization IaC, SOPS policy, brand source and legacy design history | `infra` | Private / private | MIT | 19 | `a491484` | `33122215640` |
| `mcp-server/`, owned tests/docs | `mcp-server` | Private / private | MIT | 107 | `aedee62` | `33117039555` |
| `brainzgraphinator/`, owned tests/docs | `musicbrainz-graph-enricher` | Private / private | MIT | 70 | `8613e4f` | `33122499394` |
| `brainztableinator/`, owned tests/docs | `musicbrainz-sql-loader` | Private / private | MIT | 75 | `06f2ec7` | `33122498885` |
| `dashboard/`, owned tests/docs | `operations-console` | Private / private | PolyForm Noncommercial 1.0.0 | 197 | `12099cc` | `33122498784` |
| `utilities/`, owned tests/docs | `operations-toolkit` | Private / private | MIT | 37 | `2d25ee1` | `33120062536` |
| Publishable `common/` runtime and agent-tool packages, owned tests/docs | `python-libraries` | Private / private | MIT | 155 | `28fa329` | `33043121725` |

The per-repository extraction evidence and exact filter commands are recorded in the
neighboring `groovemap-*-extraction.md` documents and each destination's
`docs/extraction.md`.

## History strategy and result

- Each source-owned code boundary was extracted in an isolated clone with
  `git filter-repo`, retaining only relevant commits and promoting the service directory
  to the destination root. The original clone was not used as an extraction target.
- `deployment` additionally imports five filtered revisions of the three root Neo4j
  maintenance scripts. The reviewed current scripts are retained while their earlier
  history remains reachable.
- `infra` is a manually bootstrapped repository. Filtered history for `design/` and
  `scripts/generate_brand_assets.py` is merged under `brand/legacy/`; current canonical
  editable branding lives under `brand/`.
- `.github` and `groovemap-music.github.io` are purpose-built organization repositories,
  not artificial copies of unrelated monorepo history.
- No source tags were copied because none unambiguously represented an independent
  destination release. No destination tags or releases have been created.

## Complete tracked top-level disposition

| Monorepo directory | Disposition |
| --- | --- |
| `.github/` | Repository-specific workflows were distributed to their owners. The organization `.github` repository owns only the profile/community-health surface; no separate automation repository was justified. |
| `.planning/` | Excluded. Its tracked contents are only `v2-gruvax/PLAN.md` and `SPEC.md`; GRUVAX is explicitly outside GrooveMap. |
| `api/` | `catalog-api` |
| `brainzgraphinator/` | `musicbrainz-graph-enricher` |
| `brainztableinator/` | `musicbrainz-sql-loader` |
| `common/` | Versioned publishable packages in `python-libraries`; consumers pin its immutable commit. |
| `dashboard/` | `operations-console` |
| `design/` | History archived in `infra/brand/legacy`; current deterministic branding source is `infra/brand`. |
| `docs/` | Distributed to the repository that owns each subject. Cross-service migration evidence remains in this source repository. |
| `explore/` | `graph-explorer` |
| `extractor/` | `catalog-ingestion` |
| `graphinator/` | `discogs-graph-enricher` |
| `insights/` | `analytics-engine` |
| `mcp-server/` | `mcp-server` |
| `schema-init/` | `database-schema` |
| `scripts/` | Functional scripts were distributed. The brand generator history is archived in `infra`; the obsolete monorepo-wide updater is excluded. The three data-maintenance scripts are in `deployment` with dry-run defaults and explicit mutation gates. |
| `secrets.example/` | `deployment`; examples contain placeholders only. |
| `static/` | Owned application assets moved with their applications. `static/fonts/` is excluded because the binaries lack sufficient license/provenance evidence. |
| `tableinator/` | `discogs-sql-loader` |
| `tests/` | Divided among functional owners. The API performance runner/image belongs to `catalog-api`; deployment retains only environment configuration and an immutable-image wrapper. |
| `utilities/` | `operations-toolkit` |

The excluded paths and reasons are machine-readable in
`infra/manifests/source-exclusions.json`.

## Docker build-unit ownership

| Original Dockerfile | Current owner | Result |
| --- | --- | --- |
| `api/Dockerfile` | `catalog-api/Dockerfile` | Builds without a sibling `common/`; private Python wheels are resolved from the pinned source commit. |
| `brainzgraphinator/Dockerfile` | `musicbrainz-graph-enricher/Dockerfile` | Independently buildable. |
| `brainztableinator/Dockerfile` | `musicbrainz-sql-loader/Dockerfile` | Independently buildable. |
| `dashboard/Dockerfile` | `operations-console/Dockerfile` | Independently buildable; owned frontend assets are local. |
| `explore/Dockerfile` | `graph-explorer/Dockerfile` | Independently buildable; owned frontend assets are local. |
| `extractor/Dockerfile` | `catalog-ingestion/Dockerfile` | Independently buildable Rust image. |
| `graphinator/Dockerfile` | `discogs-graph-enricher/Dockerfile` | Independently buildable. |
| `insights/Dockerfile` | `analytics-engine/Dockerfile` | Independently buildable. |
| `schema-init/Dockerfile` | Historical `database-schema` source; live application is a deployment operation | The versioned repository ships schema definitions/contracts, not a credential-bearing one-shot container. Earlier Dockerfile revisions remain in retained history. |
| `tableinator/Dockerfile` | `discogs-sql-loader/Dockerfile` | Independently buildable. |
| `tests/perftest/Dockerfile` | `catalog-api/performance/Dockerfile` | One canonical performance runner. `deployment` consumes only an explicitly selected image digest. |

All Python service builds have removed monorepo-relative `COPY common/` coupling. The
shared `groovemap-runtime` and `groovemap-agent-tools` packages are sourced from immutable
`python-libraries` commit `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`.

The persistence contract digest remains
`9ffd80d0d2eace50d7b7a941e0fdb26ca8614595e69d44fd227a01740bd7d8e3`.
Its six consumers record MIT-licensed producer commit
`6a29e2859a2177eebae1d97dd8550997ff43e9d0`; their gates and current CI runs pass.

## Organization governance and platform limitations

- GitHub reports the organization plan as `free`.
- Organization base permission is `none`; members cannot create repositories.
- Team `maintainers` contains `SimplicityGuy`, has `maintain` access to every repository,
  and `admin` access to the higher-risk `infra` and `deployment` repositories.
- Actions are enabled for all repositories with selected-action policy. Default workflow
  token permissions are read-only and workflows cannot approve pull requests.
- Organization variables are `GROOVEMAP_ORGANIZATION=groovemap-music` and
  `GROOVEMAP_DOMAIN=groovemap.music`.
- GitHub returns HTTP 403 for private branch protection with an upgrade requirement.
  Therefore these private repositories are honestly **unprotected**: no branch rule or
  ruleset is claimed. A paid-plan upgrade or public visibility would be required before
  such protection can be applied.
- Private GitHub Pages is unavailable on this plan. The site repository's Pages API is
  currently HTTP 404, as expected before its approved public transition and enablement.
- Two-factor authentication is not currently required organization-wide; enabling that
  policy is an owner security decision because it can remove non-compliant members.

## Verification performed

- Every destination's authoritative `just check` passed, including formatting, lint,
  type checking, unit/integration tests appropriate to the repository, source/contract
  checks, license checks, and current-tree/history secret scans.
- Clean installation and production build checks passed for each buildable destination.
  Release dry runs passed for independently versioned artifact repositories; they create
  no tag, release, package, or image. `database-schema` and `operations-toolkit` release
  dry runs were rerun after their approved MIT conversions.
- All 17 authoritative CI workflows listed above pass at their current remote heads.
- All local destination working trees are clean and synchronized with `origin/main`.
- All repositories remain private. No packages, images, tags, releases, Pages deployment,
  or DNS records were published during verification.
- Infra's local, ignored OpenTofu plan completed with exit code 0. The safety checker
  reports `Plan safety checks passed (no-op=91)`, so no apply is required or performed.
- The original monorepo is clean and exactly matches `origin/main` at
  `204f49e2429f074546dfc67e6354be2529a983ac`; every tracked source directory remains.

## Security and recovery state

- Encrypted SOPS files are restricted to the approved `secrets/*.sops.{yaml,json,env}`
  patterns. No plaintext secret, private age identity, Tofu state, plan, credential,
  signing material, or generated authentication file is tracked.
- `.sops.yaml` records only public recipients: a machine-bound Secure-Enclave
  `age-plugin-se` recipient and a separate 1Password-backed recovery recipient.
- The local project identity file is outside all repositories with mode `0600`.
- The most recent unattended check reached the expected Touch ID/Secure Enclave prompt;
  the recovery check reached the expected 1Password authorization prompt. Both were
  deliberately cancelled without printing a secret. Final operator-authorized
  decryption checks remain pending.
- OpenTofu state remains local and ignored. Provider-managed secret values can still
  appear in state even when their source is SOPS encrypted; a secure remote-state and CI
  decryption design has not been approved.

## Explicit pending approval gates

1. Authorize Touch ID for `just secrets-check`, then authorize 1Password for
   `just secrets-check-recovery`.
2. Review and approve `.github` from private to public so the organization profile can
   render. Verify the profile and shared-file inheritance afterward.
3. Review and approve `groovemap-music.github.io` from private to public, then enable
   GitHub Actions Pages and verify the GitHub Pages origin URL.
4. Approve the exact Cloudflare DNS change and rollback plan for `groovemap.music`, then
   verify DNS, the custom domain, HTTPS, internal links, assets, 404 behavior, and
   responsive layout. Current nameservers are `rachel.ns.cloudflare.com` and
   `duke.ns.cloudflare.com`; the apex has no A/AAAA/CNAME answer and HTTPS does not
   resolve.
5. Separately approve image publication. Record immutable application image digests in
   `deployment`, run the complete stack smoke test, and only then treat deployment as
   production-ready.
6. Decide whether to upgrade the GitHub plan for private-repository branch protection or
   consciously accept the documented unprotected state.

Until those gates are completed, the private repository decomposition is implemented and
verified, but the public organization profile, production site, DNS/HTTPS, and full
published-image deployment are not complete.

## Proposed second-phase monorepo cleanup

Only after every consumer uses immutable packages/images and all approval gates above are
closed:

1. freeze a final source tag and archive a read-only migration manifest;
2. verify every destination head/history and every promoted contract digest again;
3. replace migrated source directories with a concise repository index and compatibility
   notes in a separately reviewed change;
4. remove obsolete monorepo CI/workspace configuration only after no external consumer
   references it;
5. preserve licenses, notices, migration evidence, and the full Git history;
6. run the remaining source validation and link checks; and
7. archive the monorepo only if that is later approved as a separate owner action.

No content deletion or source-history rewrite is part of the initial split.
