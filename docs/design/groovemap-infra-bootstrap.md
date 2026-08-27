# GrooveMap infra bootstrap evidence

- Migration bead: `discogsography-2kpm.5`
- Evidence captured: 2026-08-27 UTC
- Repository: [`groovemap-music/infra`](https://github.com/groovemap-music/infra)
- Local clone: `/Users/Robert/workspaces/github/groovemap/infra`
- Initial revision: `a3135e2` (`feat(infra): bootstrap organization source of truth`)
- Scanner correction: `97788c0` (`fix(ci): exclude local authentication metadata from scans`)
- Review correction: `7428a6f` (`fix(infra): harden validation and preserve merge history`)
- Final merge revision: `33fd6d2` (merge of
  [`infra#1`](https://github.com/groovemap-music/infra/pull/1))

The authenticated operator was confirmed as an administrator of `groovemap-music`. The
`infra` repository returned HTTP 404 before creation, was created manually with private
visibility and no generated README, and was confirmed empty (`size: 0`) before the first
push. Its initial history was prepared in a clean clone; no monorepo path was filtered or
removed for this bootstrap task.

## Prepared source of truth

The private repository now contains the requested `.github/workflows`, `brand`,
`docs/design`, `manifests`, `scripts`, `secrets`, and `tofu` structure, plus a root
`.gitignore`, `.mise.toml`, `.sops.yaml`, `Justfile`, and `README.md`.

- mise pins OpenTofu 1.12.6, SOPS 3.13.3, age 1.3.1, age-plugin-se 0.2.1, just 1.57.0,
  GitHub CLI 2.97.0, jq 1.8.2, Node.js 24.20.0, gitleaks 8.30.1, and trufflehog 3.97.1.
- `just check` composes formatting, backend-disabled/noninteractive initialization,
  validation, deterministic branding, redacted static secret scans, and local SOPS
  decrypt-to-`/dev/null` checks. CI runs the intentionally narrower `just ci` and cannot
  decrypt, plan, or apply.
- OpenTofu pins `integrations/github` 6.13.0 in `.terraform.lock.hcl`. The manually
  created repository is import-ready as `github_repository.infra`, with
  `prevent_destroy`. Its future policy keeps merge commits and squash merging available,
  because history-preserving development may require merge commits. Import, plan, and
  apply were deliberately not run.
- State, saved plans, plaintext secret shapes, machine-bound identities, and local mise
  configuration are ignored. Plan/apply obtain `GITHUB_TOKEN` from `gh auth token` only
  for process lifetime. Documentation warns that provider values can enter state even
  when their inputs were SOPS-encrypted.
- `.sops.yaml` contains only the three approved top-level encrypted-file patterns. It has
  no recipient until the Secure Enclave and recovery design is completed in Phase 3; no
  age identity, recovery key, or encrypted example was generated here.
- Canonical GrooveMap tokens and SVG templates reproduce 12 tracked assets using pinned
  Node.js with no package dependencies. The geometry and palette derive from the
  monorepo generator. Unnoticed Space Grotesk binaries were not promoted; brand guidance
  requires verified provenance and the applicable font license before use.
- The validate-only workflow pins actions by full commit, checks out with
  `persist-credentials: false`, grants only `contents: read`, and cancels superseded runs
  using a workflow-and-ref concurrency group.

## Verification evidence

The following gates passed at final merge revision `33fd6d2` without printing credential
values:

```text
mise exec -- just doctor        PASS (SOPS identity reported pending as designed)
bash -n scripts/*.sh            PASS
xmllint --noout brand/assets/*.svg
                                PASS
mise exec -- just check         PASS
  tofu fmt -check -recursive    PASS
  tofu init -backend=false      PASS
  tofu validate                 PASS, no warnings
  deterministic brand check    PASS, 12 assets
  gitleaks + trufflehog         PASS, redacted output policy
  encrypted secret check       PASS, no ciphertext files yet
GitHub Actions PR Validate      PASS, run 33031625013
GitHub Actions main Validate    PASS, run 33031665579
git status --short              CLEAN
```

The first CI run correctly exposed that a filesystem scanner could inspect GitHub
Actions' ephemeral `.git/config` authorization metadata. Revision `97788c0` excludes
`.git` and downloaded `.terraform` content from the filesystem-only trufflehog pass while
retaining gitleaks coverage and scanning all repository-owned source. The successful
replacement run is <https://github.com/groovemap-music/infra/actions/runs/33031138403>.

Review feedback was corrected on branch `fix/review-hardening` and merged through
[`infra#1`](https://github.com/groovemap-music/infra/pull/1) with a merge commit after its
validate-only check passed. The final `main` run is
<https://github.com/groovemap-music/infra/actions/runs/33031665579>.

No OpenTofu import/plan/apply, organization setting, DNS record, Pages configuration,
public visibility transition, package publication, release, secret creation, or other
destination repository was performed by this bead.
