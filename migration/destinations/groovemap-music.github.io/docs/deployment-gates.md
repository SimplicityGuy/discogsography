# Pages deployment gates

No item in this document authorizes an external change. The repository is prepared
private-first and the gates below are intentionally independent.

## Current state

- Repository creation: **not performed**.
- Initial push: **not performed**.
- Public visibility: **not approved**.
- Pages source (`GitHub Actions`): **not enabled**.
- Custom domain (`groovemap.music`): **not configured in Pages**.
- DNS: **not changed**.
- Enforce HTTPS: **not enabled**.
- Deployment workflow: **staged with a `.disabled` suffix**.

The `groovemap-music` organization is on GitHub Free. Pages cannot deploy from this
private organization repository on that plan. The repository must remain private and
Pages-disabled until the content/exposure review approves a public transition, or the
organization upgrades to a plan that supports the intended source visibility.

## Approval sequence

1. Review this tree for secrets, private links, licensing, attribution, accessibility,
   metadata, and intended public exposure.
2. Approve and create `groovemap-music/groovemap-music.github.io` as private with
   `auto_init = false`, then push only the validated prepared history through a reviewed
   pull request.
3. Verify private-repository settings and CI. Approve public visibility as a distinct
   OpenTofu change. Capture the current visibility and an owner-reviewed rollback plan.
4. Verify the `groovemap.music` domain in the organization account. Approve Pages
   configuration with GitHub Actions as source and custom domain `groovemap.music`.
5. Rename `.github/workflows/pages.yml.disabled` to `pages.yml` in a reviewed change.
6. Before DNS mutation, inventory the live apex and `www` records, TTLs, provider, and
   rollback values. Review the complete OpenTofu plan, then obtain explicit DNS approval.
7. After DNS propagates, verify the Pages deployment URL, apex and `www` behavior,
   certificate issuance, asset paths, internal links, responsive layout, and the 404
   page. Approve HTTPS enforcement only after certificate health is confirmed.

Do not configure DNS before the custom domain is secured in GitHub Pages; GitHub warns
that this ordering can create a domain-takeover window. Do not add wildcard DNS records.

## Activation verification

Run and record:

```sh
just setup
just check
git status --short
gh repo view groovemap-music/groovemap-music.github.io \
  --json nameWithOwner,visibility,defaultBranchRef,url
gh api repos/groovemap-music/groovemap-music.github.io/pages
curl --fail --silent --show-error --location --output /dev/null https://groovemap.music/
curl --fail --silent --show-error --location --output /dev/null https://groovemap.music/about/
curl --fail --silent --show-error --location --output /dev/null https://groovemap.music/404.html
```

Inspect both desktop and mobile layouts, keyboard navigation, reduced-motion behavior,
the rendered Open Graph image, sitemap, robots, manifest, favicon, and canonical URLs.
An empty post-apply OpenTofu plan is required before the migration can be called complete.
