# GrooveMap repository validation and release standards

- Status: accepted migration implementation standard
- GitHub organization: `groovemap-music`
- Product display name: GrooveMap
- Canonical website: `https://groovemap.music`
- Applies to: repositories extracted from `SimplicityGuy/discogsography`

This document is the copy-and-adapt baseline for each destination extraction. It defines
a stable developer interface and security floor without requiring unrelated repositories
to use identical internal tooling. The extraction owner must record justified deviations
in that repository's README or an architecture decision.

## Safety and migration invariants

Every destination begins private and empty (`auto_init = false`). Extraction must retain
relevant Git history with a recorded, reproducible `git filter-repo` (or equivalent)
command. The original monorepo and its history remain unchanged until every destination
has passed independent verification and a later cleanup is approved.

During migration, validation and release dry-runs may build artifacts locally or upload
short-lived workflow artifacts. They must not push images, publish packages, create
GitHub Releases, create tags, sign production artifacts, deploy, or alter external state.
Those actions require a separately reviewed release design and explicit authorization.

Never commit or log plaintext secrets, private age identities, OpenTofu state or plans,
credentials, signing material, package tokens, generated authentication files, or secrets
embedded in dependency URLs. Secret scanning reports locations and rule identifiers, not
matched values.

## Canonical repository decisions

The license named below applies to the extracted current tree only where GrooveMap owns
the rights. History filtering must preserve historical license files. Third-party,
vendored, font, and generated-content obligations follow their content into a destination
regardless of the first-party license.

| Repository | First-party license | Release authority |
| --- | --- | --- |
| `python-libraries` | MIT | Python package versions |
| `catalog-ingestion` | MIT | Rust binary and container version |
| `discogs-graph-enricher` | MIT | Deployable container version |
| `discogs-sql-loader` | MIT | Deployable container version |
| `musicbrainz-graph-enricher` | MIT | Deployable container version |
| `musicbrainz-sql-loader` | MIT | Deployable container version |
| `analytics-engine` | PolyForm Noncommercial 1.0.0 | Deployable container version |
| `graph-explorer` | PolyForm Noncommercial 1.0.0 | Deployable application version |
| `catalog-api` | Existing license pending explicit decision | Deployable container version |
| `operations-console` | Existing license pending explicit decision | Deployable container version |
| `database-schema` | Existing license pending explicit decision | Schema compatibility version |
| `operations-toolkit` | Existing license pending explicit decision | CLI package version |
| `mcp-server` | Existing license pending explicit decision | Server package or container version |
| `infra` | Existing license pending explicit decision | Unversioned configuration repository |
| `deployment` | Existing license pending explicit decision | Unversioned environment configuration |
| `.github` | Existing license pending explicit decision | Unversioned community-health content |
| `groovemap-music.github.io` | Existing license pending explicit decision | Unversioned Pages deployment |

"Existing license pending explicit decision" means preserve the source license during
extraction; it does not authorize relicensing. A repository marked unversioned does not
get Commitizen bump or release recipes. The Pages site may expose a build identifier but
does not create product version tags solely for deployments.

## Required repository contract

Every code repository contains, at minimum:

- `README.md` with setup, development, validation, build, architecture boundary,
  dependency, license, and migration-history notes;
- `Justfile` or `justfile` whose default recipe lists commands;
- `just setup`, `just check`, `just test`, and `just build`;
- an ecosystem manifest, exact toolchain selection, and committed dependency lockfile;
- `.github/workflows/ci.yml` with read-only default permissions;
- `CODEOWNERS`, with rules matching the actual team/access boundary;
- `AGENTS.md` when repository-specific instructions add information not already inherited;
- `LICENSE` and all applicable `NOTICE`, attribution, and vendored-license files;
- `.gitignore` entries for local secrets, credentials, state, caches, and build output.

The bare `just` command must be safe and display the command list. `setup`, `check`,
`test`, and `build` must be noninteractive. `check` is the fast authoritative pre-merge
gate and must work from a clean checkout after `setup`. It composes deterministic local
format checks, lint, type checking, unit tests, build validation, schema validation, and
license/notice checks that apply to that repository.

Network vulnerability databases, multi-platform builds, signing, publication, deployment,
load tests, live-service integration tests, and production OpenTofu operations are not
part of `check`. Give them explicit names such as `audit`, `test-integration`,
`build-platforms`, `release-dry-run`, or `tofu-plan` so a fast gate does not acquire
hidden credentials or external side effects.

### Universal Justfile shape

Start each repository with this interface, then fill the ecosystem commands from the
following sections. Do not keep recipes that do not describe a real capability.

```just
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install exactly what the committed lockfile describes.
setup:
    {{SETUP_COMMAND}}

# Fast, deterministic, credential-free pre-merge gate.
check: format-check lint typecheck test build license-check

test:
    {{TEST_COMMAND}}

build:
    {{BUILD_COMMAND}}

format-check:
    {{FORMAT_CHECK_COMMAND}}

lint:
    {{LINT_COMMAND}}

typecheck:
    {{TYPECHECK_COMMAND}}

license-check:
    {{LICENSE_CHECK_COMMAND}}

# Network access is intentional and separate from check.
audit:
    {{AUDIT_COMMAND}}
```

Use a successful no-op such as `@echo "No separate type checker"` only when the README
explains why the capability does not apply. Never hide a missing test suite behind a no-op.

## Ecosystem templates

### Python and uv

Python repositories retain `pyproject.toml`, the Hatchling build backend where applicable,
Ruff, mypy, pytest, and a repository-local `uv.lock`. Record an exact CPython patch in
`.python-version` or `.mise.toml`; `requires-python` remains a compatibility constraint,
not the toolchain pin. Run Python tools only through `uv run` and use `--frozen` in CI.

```just
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

setup:
    uv sync --all-extras --dev --frozen

check: format-check lint typecheck test build license-check

format-check:
    uv run ruff format --check .

lint:
    uv run ruff check .

typecheck:
    uv run mypy .

test:
    uv run pytest -m "not integration and not e2e"

build:
    uv build

license-check:
    uv run python scripts/check_licenses.py

audit:
    uv run pip-audit
```

Services that do not publish a Python distribution may replace `uv build` with a package
import check and container build validation. The command still must prove that the
production unit can be assembled. Private `groovemap-music/python-libraries` references
must be explicit, version-tagged Git dependencies locked to immutable commits by
`uv.lock`; editable path dependencies are development-only and may not enter CI or image
builds.

For a versioned Python package, use its PEP 621 version as authority. With uv, Commitizen's
`uv` version provider updates both `pyproject.toml` and `uv.lock`:

```toml
[tool.commitizen]
name = "cz_conventional_commits"
version_provider = "uv"
version_scheme = "pep440"
tag_format = "v$version"
annotated_tag = true
update_changelog_on_bump = true
changelog_file = "CHANGELOG.md"
```

### Rust

Rust repositories retain `Cargo.toml`, `Cargo.lock`, formatting and Clippy policy, and an
exact `rust-toolchain.toml` channel. A floating `stable` channel is not a pin. Commit
`cargo-deny` configuration for dependency licenses and bans where used.

```just
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

setup:
    cargo fetch --locked

check: format-check lint test build license-check

format-check:
    cargo fmt --all --check

lint:
    cargo clippy --all-targets --all-features --locked -- -D warnings

typecheck:
    cargo check --all-targets --all-features --locked

test:
    cargo test --all-targets --all-features --locked

build:
    cargo build --release --locked

license-check:
    cargo deny check licenses bans sources

audit:
    cargo audit
```

For `catalog-ingestion`, Cargo package metadata is the version authority. Configure
Commitizen with `version_provider = "cargo"`, `version_scheme = "semver2"`, and
`tag_format = "v$version"`. Add a pre-bump hook only if the chosen provider does not
refresh every synchronized manifest or lockfile; the hook must fail if it leaves version
metadata inconsistent.

### Node, browser applications, and Astro

Node repositories commit `package-lock.json`, use `npm ci`, and set an exact
`packageManager` value such as `npm@<exact-version>` in `package.json`. Pin the Node patch
in `.node-version`, `.mise.toml`, or the equivalent checked-in toolchain file. An
`engines.node` range documents compatibility but is not a pin.

```just
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

setup:
    npm ci

check: format-check lint typecheck test build license-check

format-check:
    npm run format:check

lint:
    npm run lint

typecheck:
    npm run typecheck

test:
    npm test -- --run

build:
    npm run build

license-check:
    npm run licenses:check

dev:
    npm run dev

preview:
    npm run preview

audit:
    npm audit --audit-level=high
```

The Astro organization site is static, uses `site: "https://groovemap.music"`, has no
repository base path, and validates its generated links and assets after `astro build`.
It is unversioned: do not add Commitizen bump/release recipes. Its Pages workflow is a
deployment workflow, not a general release workflow, and remains disabled until the
private-to-public and Pages gates are separately approved.

For a versioned Node package, use `version_provider = "npm"` and `version_scheme =
"semver2"`. A multi-artifact browser/container product instead uses one explicit
`VERSION` file and lists every synchronized manifest in Commitizen `version_files`.

### Containers

Container-owning repositories add these recipes to their primary ecosystem Justfile:

```just
image := "groovemap-local/{{REPOSITORY}}:dev"

image-build:
    docker buildx build --load --tag {{image}} .

image-check:
    docker run --rm aquasec/trivy:<PINNED_VERSION> image \
        --exit-code 1 --severity HIGH,CRITICAL {{image}}

sbom:
    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
        anchore/syft:<PINNED_VERSION> {{image}} -o spdx-json=dist/sbom.spdx.json

build-platforms:
    docker buildx bake --file docker-bake.hcl --print
```

The extraction replaces image placeholders with the canonical
`ghcr.io/groovemap-music/<repository>` name but does not push. Dockerfiles pin base images
by digest, use multi-stage builds, run as a numeric non-root user, exclude credentials via
`.dockerignore`, and use BuildKit secret or SSH mounts for private dependencies. Never
pass tokens through `ARG`, `ENV`, build context files, cache keys, image labels, or remote
URLs. `just check` may validate a single local production image when that is fast; network
scanning, SBOM generation, and the full platform matrix remain explicit release gates.

### OpenTofu and encrypted configuration

`infra` and OpenTofu-owning repositories pin OpenTofu, SOPS, age, `age-plugin-se`, just,
gh, jq, and scripting runtimes in `.mise.toml`. Commit `.terraform.lock.hcl`; ignore
`.terraform/`, `*.tfstate*`, saved plan files, crash logs, and override files. The normal
CI gate does not decrypt secrets or touch state:

```just
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

setup:
    mise install

check: format-check init-offline validate secrets-metadata-check

format-check:
    tofu fmt -check -recursive

init-offline:
    tofu -chdir=tofu init -backend=false -input=false

validate:
    tofu -chdir=tofu validate

test:
    just validate

build:
    just validate

secrets-metadata-check:
    scripts/check-sops-files.sh --metadata-only

plan:
    #!/usr/bin/env bash
    export GITHUB_TOKEN="$(gh auth token)"
    tofu -chdir=tofu plan -input=false

apply:
    #!/usr/bin/env bash
    export GITHUB_TOKEN="$(gh auth token)"
    tofu -chdir=tofu apply -input=false
```

`plan` and `apply` remain operator-local until CI identity, SOPS decryption, state
storage, redaction, approval, and recovery are designed. Provider secrets can appear in
state even when their source documents are SOPS-encrypted. Do not save a plan by default.

## Dependency and automation pinning

The following are required before an extraction is accepted:

| Surface | Required pin |
| --- | --- |
| Python | Exact runtime patch plus committed `uv.lock`; CI uses `uv sync --frozen` |
| Rust | Exact `rust-toolchain.toml` channel plus committed `Cargo.lock`; use `--locked` |
| Node | Exact Node patch, exact `packageManager`, and committed `package-lock.json`; use `npm ci` |
| Containers | Base images by digest; tool images by immutable digest where practical |
| OpenTofu | `.mise.toml` versions, provider constraints, and `.terraform.lock.hcl` |
| GitHub Actions | Full 40-character commit SHA with a reviewed release tag comment |

Renovate or Dependabot may update pins later, but an updater does not excuse an unpinned
initial extraction. Never copy an Action's moving major tag into a workflow. Resolve the
current upstream commit during extraction and review action source/permissions before
using it.

## Validation CI template

Each repository adapts this minimal workflow. It deliberately receives no write
permission or real secret. Replace every `PIN_*_SHA` marker with a reviewed 40-character
commit SHA before committing the destination workflow.

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Check out source
        uses: actions/checkout@PIN_CHECKOUT_SHA
        with:
          persist-credentials: false
      - name: Set up repository toolchain
        uses: jdx/mise-action@PIN_MISE_ACTION_SHA
      - name: Run authoritative gate
        run: just setup && just check
```

Set permissions at workflow level to none/read and add job-local writes only when a job
needs them. Pull-request CI must not expose organization secrets to untrusted code. Pin
runner images where reproducible build risk justifies it, and always set job timeouts.
Caches are performance aids, never sources of truth; lockfiles remain authoritative and
cache keys include their hashes.

The organization is currently on GitHub Free. GitHub artifact attestations for private
repositories require Enterprise Cloud, so the migration must not claim that GitHub-hosted
provenance exists. Generate local SBOMs and checksums during release dry-runs. Revisit
GitHub attestations if a repository becomes public or the plan changes.

## Private dependency authentication

Prefer the built-in `GITHUB_TOKEN` for the current repository. It cannot read a different
private repository, so cross-repository dependency access uses a narrowly installed
organization-owned GitHub App with read-only Contents access to only the required source
repositories. The workflow creates a short-lived installation token; no PAT is accepted.

```yaml
permissions:
  contents: read

steps:
  - name: Create private dependency token
    id: dependency-token
    uses: actions/create-github-app-token@PIN_APP_TOKEN_ACTION_SHA
    with:
      client-id: ${{ vars.DEPENDENCY_APP_CLIENT_ID }}
      private-key: ${{ secrets.DEPENDENCY_APP_PRIVATE_KEY }}
      owner: groovemap-music
      repositories: python-libraries

  - name: Check out source
    uses: actions/checkout@PIN_CHECKOUT_SHA
    with:
      persist-credentials: false

  - name: Install locked dependencies
    env:
      GIT_CONFIG_COUNT: "1"
      GIT_CONFIG_KEY_0: url.https://x-access-token:${{ steps.dependency-token.outputs.token }}@github.com/.insteadOf
      GIT_CONFIG_VALUE_0: https://github.com/
    run: just setup
```

The App installation must be narrowed to the consumer and dependency repositories. Its
key is stored as an Actions secret only after the CI trust design is approved. The
environment-scoped Git configuration avoids writing the installation token to a
credential file. Masking does not make a token safe to print; commands must not enable
shell tracing. Prefer an ephemeral credential helper if the ecosystem supports one.
Docker builds receive the token through a BuildKit secret or SSH mount and remove any
temporary Git configuration in the same layer.

## Secrets, licenses, notices, and supply-chain gates

The extraction acceptance gate includes:

1. Scan the current tracked tree and the filtered history with an offline-capable secret
   scanner. Store only redacted findings and allowlist entries with a rule, path, and
   justification.
1. Confirm no `.env`, credentials, private keys, SOPS identities, state, plans, caches,
   build output, editor files, or generated authentication files are tracked.
1. Verify the first-party `LICENSE` matches the approved boundary and historical license
   commits remain reachable where relevant.
1. Copy all applicable `NOTICE`, font licenses, vendored licenses, source offers, and
   attribution. A dependency license report is not a substitute for bundled-asset review.
1. Generate an SPDX or CycloneDX SBOM from the locked production dependency graph and
   built artifact. Verify that it contains the repository name, source commit, tool
   version, and artifact digest without credentials or machine-local paths.
1. Generate SHA-256 checksums and a local provenance statement during `release-dry-run`.
   Do not sign, attest remotely, upload, or publish during migration.

`just license-check` is deterministic and validates policy against committed manifests.
`just audit` may access advisory databases and reports vulnerabilities separately. An
exception file must identify the advisory/license, affected component, owner, rationale,
expiry, and compensating control; blanket ignores are rejected.

## Ownership and repository instructions

`CODEOWNERS` encodes the real access and review boundary, not a directory-shaped fiction.
Use an organization team rather than a personal account once the team exists:

```text
# Replace with the narrowest owning team provisioned by infra.
* @groovemap-music/maintainers

# Examples only; include them when the paths and specialist teams exist.
/.github/ @groovemap-music/platform
/migrations/ @groovemap-music/data-platform
/security/ @groovemap-music/security
```

Do not add nonexistent teams to an initial commit. Until OpenTofu creates the team, use a
reviewed temporary owner or stage the file locally and activate it after provisioning.
On GitHub Free, private repositories remain honestly documented as unprotected; a
`CODEOWNERS` file alone does not require review.

Repository `AGENTS.md` files describe only local build/test commands, architecture
boundaries, generated-code ownership, and safety constraints. Do not blindly copy the
monorepo's Beadhive instructions into a destination unless that destination has been
onboarded as its own hive. Avoid instructions that contain host-specific paths, secrets,
temporary migration credentials, or obsolete monorepo-relative commands.

## Merge and history policy

Repositories must keep merge commits available. The default landing workflow uses a
reviewed pull request and a non-fast-forward merge where the development protocol needs
to preserve branch or AGF molecule history. Do not configure squash-only merging for
those repositories. Squash remains an optional project decision only when it does not
destroy the history semantics being preserved.

Suggested repository settings are:

- allow merge commits: yes;
- allow squash merge: per repository, never the only AGF-compatible method;
- allow rebase merge: per repository;
- automatically delete merged head branches: yes;
- require linear history: no where merge commits are part of the protocol;
- default branch: `main` after the prepared history is pushed.

Extraction filtering preserves source commits; it does not rewrite them to Conventional
Commits. Conventional Commit validation starts at the destination's migration boundary,
so historical subjects do not block the initial import.

## Commitizen and versioned artifacts

Add Commitizen only to repositories with a release authority in the table above. Use
Conventional Commits, `v$version` tags, an annotated tag, and a checked-in changelog.
Version authority is one of:

- Python/uv: PEP 621 version via Commitizen's `uv` provider;
- Rust: Cargo package version via the `cargo` provider;
- Node package: package metadata via the `npm` provider;
- synchronized multi-artifact product: explicit `VERSION` file plus controlled
  `version_files` entries.

Add these safe recipes after adapting the tool runner (`uv run cz` for Python projects or
an exactly pinned standalone environment elsewhere):

```just
# Prints the proposed version, tag, increment, and changelog changes; writes nothing.
bump-preview:
    {{CZ}} bump --dry-run --changelog --yes

# Mutates version/changelog and creates the local release commit/tag. Never pushes.
bump:
    {{CZ}} bump --changelog

# Builds, tests, inventories, and checksums without publishing or signing.
release-dry-run: check sbom
    scripts/build-release-artifacts.sh --output dist
    shasum -a 256 dist/* > dist/SHA256SUMS
    scripts/write-local-provenance.sh --output dist/provenance.json
```

Before `bump`, require a clean tree and successful `check`. Configure Commitizen hooks
only to synchronize controlled manifests/lockfiles, and verify afterward that every
version source agrees. Set `annotated_tag = true` in every versioned repository so
Commitizen creates an annotated `v$version` tag. No migration workflow pushes that tag.

The release dry-run is valid only when it builds from a clean checkout of the exact
candidate commit, runs the full gate, produces required notices, SBOMs, checksums, and
local provenance, and leaves the repository unchanged except for ignored `dist/` output.

## Future release workflow contract

A real release workflow is added but kept disabled or publication-free until separately
authorized. When activated, it must:

- trigger only from an approved `v*` tag or explicit dispatch with an environment approval;
- check that the annotated tag resolves to the checked-out commit and version metadata;
- build from the tag, run `release-dry-run`, and publish the already verified bytes;
- default to `contents: read` and grant only job-local permissions;
- use `packages: write`, `contents: write`, `id-token: write`, or `attestations: write`
  only in the job that needs each permission;
- prefer registry or cloud OIDC trusted publishing over stored registry tokens;
- use a narrowly installed GitHub App for unavoidable cross-repository automation;
- use an approved GitHub environment and concurrency to serialize releases;
- never run arbitrary pull-request code with publishing credentials.

The migration version contains build/test/package jobs only and ends before publication.
It may upload short-lived workflow artifacts with `actions/upload-artifact` pinned to a
reviewed commit, but it may not publish to GHCR, a language registry, GitHub Releases,
Pages, or a deployment target.

## Extraction acceptance checklist

An extraction task may submit a destination for review only when all applicable items are
recorded with command output or other evidence:

- [ ] Filter command, path rewrites, retained commit count, and tag policy are documented.
- [ ] Source monorepo remains clean and unchanged.
- [ ] Canonical URLs use `groovemap-music`; the website uses `groovemap.music`.
- [ ] `LICENSE`, notices, attribution, and vendored obligations match the approved boundary.
- [ ] Exact toolchains, Actions, base images, and dependency lockfiles are committed.
- [ ] Clean-checkout `just setup`, `just check`, `just test`, and `just build` pass.
- [ ] Secret scans cover the staged tree and filtered history without exposing matches.
- [ ] Cross-repository dependencies use explicit versions or documented local linking.
- [ ] CI has least privilege and passes without real production secrets.
- [ ] `release-dry-run` passes for a versioned artifact and publishes nothing.
- [ ] Commitizen is absent for unversioned repositories.
- [ ] Working tree is clean after validation; ignored outputs contain no credentials.
- [ ] No repository, package, release, tag, image, deployment, visibility, Pages, or DNS
      mutation occurred beyond the separately approved action.

## Upstream references

- [Commitizen bump command](https://commitizen-tools.github.io/commitizen/commands/bump/)
- [Commitizen version providers](https://commitizen-tools.github.io/commitizen/config/version_provider/)
- [GitHub App authentication in Actions](https://docs.github.com/en/enterprise-cloud@latest/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow)
- [GitHub Actions security](https://docs.github.com/en/actions/how-tos/secure-your-work)
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)

Last updated: 2026-08-27
