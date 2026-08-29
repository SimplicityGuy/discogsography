# GrooveMap organization site

This is the static Astro source for [groovemap.music](https://groovemap.music), the
organization website for `groovemap-music`. It introduces GrooveMap's music knowledge
graph and links visitors to the project's public work.

> Migration state: locally prepared only. The GitHub repository does not yet exist, this
> tree has not been pushed, and public visibility, Pages, custom-domain settings, DNS,
> and HTTPS are all separate approval gates.

## Architecture boundary

Astro prerenders every route to static HTML. There is no server adapter, client-side
application runtime, secret, authentication flow, analytics collector, or environment-
dependent content. The canonical URL is `https://groovemap.music`; this organization
site is served from `/`, so `astro.config.mjs` intentionally has no `base` property.

Canonical editable design tokens and templates live in the private
`groovemap-music/infra` repository. Files under `public/brand` are promoted,
deterministic render outputs. `public/brand/provenance.json` records the source revision,
path, and SHA-256 digest for every promoted asset.

## Setup and development

Install the pinned toolchain with mise, then use the stable `just` interface:

```sh
mise install
just setup
just dev
```

The package lock is authoritative. `just setup` uses `npm ci`; do not replace it with an
unlocked install in CI.

## Validation and build

```sh
just check
just test
just build
just preview
```

`just check` runs formatting, Astro-aware lint and type checks, unit tests, a production
build, generated HTML/accessibility/link/asset/metadata validation, and a locked-
dependency license policy check. `just audit` is separate because it intentionally
contacts an advisory service.

The generated site is written to ignored `dist/`. Local preview is a static-file check;
it does not emulate GitHub Pages configuration or DNS.

## Deployment

The official Astro/Pages workflow is staged as
`.github/workflows/pages.yml.disabled`. GitHub ignores that filename, so it cannot deploy.
After all approvals in [deployment-gates.md](docs/deployment-gates.md), activation is a
reviewed rename to `pages.yml`. The staged workflow uses only fully pinned Actions,
the `github-pages` environment, deployment concurrency, and the minimum deployment
permissions (`contents: read`, `pages: write`, `id-token: write`).

`public/CNAME` documents the intended custom domain and follows Astro's deployment
guidance. GitHub's current custom-workflow behavior still requires configuring the domain
in Pages settings; a CNAME file alone does not mutate that setting or DNS.

## Versioning, release, and license

This website is an unversioned deployment unit. It does not publish a package or other
meaningful versioned artifact, so Commitizen bump and release recipes are intentionally
absent. A Pages deployment is not a product release.

The first-party license is preserved from the source monorepo pending an explicit license
decision. See `LICENSE`. Promoted brand SVGs use system font names and embed no font
software; the source monorepo's unnotified Space Grotesk binaries were not promoted.

## Migration history

There was no pre-existing Astro organization-site path to filter from the monorepo. The
destination begins with this reviewed site tree rather than manufacturing unrelated
history. Brand asset lineage is retained through the infra commit and byte digests in
`public/brand/provenance.json`. The original monorepo remains unchanged.
