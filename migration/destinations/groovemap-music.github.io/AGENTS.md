# Repository instructions

This repository is the static GrooveMap organization site. It has no server runtime and
must never depend on secrets at build or run time.

- Use the exact Node/npm versions declared in `.node-version` and `package.json`.
- Run `just check` before proposing a change.
- Keep `astro.config.mjs` in static-output mode with `site` set to
  `https://groovemap.music`; do not add a repository `base` path.
- Treat `infra/brand` as the editable source for files under `public/brand`. Promote
  deterministic render outputs and update `public/brand/provenance.json`; do not edit
  promoted SVGs independently.
- Keep internal links root-relative and accessible without client-side JavaScript.
- Do not activate the staged Pages workflow, publish the repository, enable Pages, or
  change DNS without the separate approvals documented in `docs/deployment-gates.md`.
