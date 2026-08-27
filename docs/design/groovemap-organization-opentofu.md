# GrooveMap organization OpenTofu evidence

Date: 2026-08-27

The private `groovemap-music/infra` repository is the organization source of truth. Its
canonical manifest declares 17 repositories, all initially private and created without an
auto-generated commit. The manually bootstrapped `infra` repository was imported rather
than recreated.

## Applied scope

- GitHub organization settings, including `none` default member access and disabled member
  repository creation, Pages creation, private forking, and organization/repository projects;
- a `maintainers` team with `SimplicityGuy` as a member and access to all 17 repositories;
- repository descriptions, topics, merge policy, issue settings, and private visibility;
- organization Actions policy and read-only workflow-token defaults;
- organization/domain Actions variables containing non-secret values;
- vulnerability alerts, Dependabot security updates, and the canonical issue labels.

GitHub Free was detected. Private-repository rulesets and private Pages are unsupported on
this plan, so neither is declared or claimed. DNS, public visibility, Pages enablement,
Actions secrets, remote state, packages, and releases remain outside this apply.

## Apply and recovery record

The reviewed initial plan contained one import, 90 additions, one in-place update, and no
deletions. The first apply created the 16 empty destination repositories but GitHub rejected
an explicit repository-level `allow_forking = false` field because private forking was
already forbidden organization-wide. OpenTofu's `prevent_destroy` lifecycle guard blocked
the tainted resources from being replaced.

Each live repository was confirmed private with a matching state ID. Only the 16 stale
local taint markers were cleared. Infra PR #4 then omitted the redundant repository field
and updated the plan guard to permit both the initial one-time import and later state-backed
plans. Validate-only CI passed before merge.

The remaining reviewed plan contained 67 additions, one in-place organization update, and
no deletions; all 17 repository resources were no-ops. The apply completed with exactly
`67 added, 1 changed, 0 destroyed`.

## Verification evidence

- `mise exec -- just check` passed in `groovemap-music/infra`.
- The post-apply `tofu plan -detailed-exitcode` returned `0`, proving no pending changes.
- GitHub reported exactly 17 repositories and no non-private repository.
- Only `infra` has a default branch; every newly created destination remains empty.
- The organization reports GitHub Free, `default_repository_permission=none`, repository
  creation disabled, private forking disabled, and organization/repository projects disabled.
- The `maintainers` team has access to all 17 repositories.
- The original `SimplicityGuy/discogsography` monorepo was not modified by extraction or
  cleanup as part of this work.

Local OpenTofu state and saved plans remain ignored and operator-local. They can contain
sensitive provider inputs in future phases even when those inputs originate in SOPS-encrypted
files; a secure remote-state and CI identity/decryption design is still required before live
plan or apply is enabled in CI.
