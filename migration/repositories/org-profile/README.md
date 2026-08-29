# GrooveMap organization profile

This is the prepared source tree for `groovemap-music/.github`. GitHub renders
[`profile/README.md`](profile/README.md) on the organization's public profile only after
this repository is deliberately made public.

The repository starts private. Creating it, pushing this prepared history, changing its
visibility, and editing the organization avatar are separate migration gates. The
publication checklist in [`docs/publication-runbook.md`](docs/publication-runbook.md)
must be completed before any public transition.

## Develop and validate

The repository has no package dependencies. Node.js and `just` are pinned in
[`.mise.toml`](.mise.toml), and validation uses only Node's standard library.

```sh
mise install
just check
```

`just check` verifies Markdown and local links, promoted-asset integrity, the preserved
license, community-health scope, and the explicit public-exposure allowlist. It does not
make network requests or change external state.

## Ownership boundaries

- `groovemap-music/infra` owns editable brand tokens, templates, and rendering.
- This repository owns only promoted profile assets and community-health content.
- The organization owner controls the GitHub organization avatar through an owner-only
  GitHub interface; the `.github` repository does not set it.
- No shared community-health files are enabled initially. See
  [`docs/community-health.md`](docs/community-health.md).

This repository is unversioned because it publishes no independently versioned artifact.
It intentionally has no Commitizen or release workflow.
