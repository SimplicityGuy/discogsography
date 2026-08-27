# GrooveMap organization governance baseline

- Status: accepted migration baseline
- Evidence captured: 2026-08-27 UTC
- GitHub organization: [`groovemap-music`](https://github.com/groovemap-music)
- Product display name: GrooveMap
- Primary maintainer: [`SimplicityGuy`](https://github.com/SimplicityGuy)
- Website domain: `groovemap.music`
- Preparation workspace: `/Users/Robert/workspaces/github/groovemap`

This record replaces `groovemap` with `groovemap-music` as the canonical GitHub
namespace. The existing `GrooveMap` organization is controlled by another party and is
not a migration target. Repository names, package URLs, image names, Pages configuration,
and documentation must use `groovemap-music` unless a registry imposes a different name.

## Read-only organization evidence

The following facts were queried through the authenticated GitHub API without changing
authentication scopes or organization state:

| Check | Observed state | Consequence |
| --- | --- | --- |
| Membership | `SimplicityGuy` is an active organization `admin` | The primary maintainer is an organization owner. |
| GraphQL administration | `viewerCanAdminister: true` | The authenticated operator can administer the organization. |
| Plan | GitHub Free for organizations; one filled seat | Private repositories have the Free plan's limited feature set. |
| Repositories | Zero repositories | No destination repository predates this migration. |
| Base permission | `read` | A later reviewed organization-settings change must deliberately retain or reduce this permission. |
| Member repository creation | Enabled | A later reviewed organization-settings change must decide whether repository creation is restricted to IaC. |
| Two-factor authentication | Not required | The organization does not currently enforce 2FA; this must not be represented as enforced. |
| Organization rulesets API | HTTP 403: `Upgrade to GitHub Team to enable this feature.` | Organization rulesets cannot be applied on the current plan. |
| Organization profile name | Not explicitly configured | A later owner/IaC action should set the display name to `GrooveMap`. |

The evidence commands intentionally select non-secret fields. Authentication continues to
come from `gh` at execution time; no token value or generated credential belongs in Git,
OpenTofu input files, or documentation.

## Plan limitations

GitHub Free supports rulesets and protected branches for public repositories, but not for
private repositories. The migration therefore must report every private destination as
**unprotected** while this plan remains active; a ruleset declared in configuration but
rejected or not enforced is not a protection. Upgrade to GitHub Team or Enterprise before
requiring private-repository rulesets or branch protection.

GitHub Pages on the Free organization plan requires a public source repository. Pages from
a private source repository requires Team or Enterprise, and a privately published Pages
site requires Enterprise Cloud. In addition, Pages access control applies to project sites,
not the root organization site. Consequently, `groovemap-music.github.io` must remain
private and Pages-disabled until its content has passed exposure review and its public
transition has separate approval. The expected organization site is public after that
transition.

Authoritative feature references:

- [Ruleset availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [Protected branch availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)
- [GitHub Pages plan availability](https://docs.github.com/en/pages/getting-started-with-github-pages)
- [GitHub Pages visibility and access control](https://docs.github.com/en/enterprise-cloud@latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site)

## Domain evidence and DNS gate

The maintainer has identified `groovemap.music` as a domain they control. Public registry
data records Namecheap as registrar and delegates DNS to Cloudflare nameservers
`duke.ns.cloudflare.com` and `rachel.ns.cloudflare.com`. At evidence capture time, the apex
had no A, AAAA, or CNAME answer. The registry data and maintainer statement identify the
intended domain, but read-only public DNS cannot prove account-level access to either the
registrar or Cloudflare.

Before any DNS change, the operator must demonstrate provider access, review the proposed
record set and rollback values, and explicitly approve the change. Pages custom-domain and
HTTPS configuration must be reviewed together with DNS. DNSSEC is currently reported as
unsigned and must not be described as enabled.

## Private-first and approval boundaries

- Every destination repository, including `.github` and
  `groovemap-music.github.io`, begins private with `auto_init = false`.
- `infra` remains private permanently and becomes the declarative source of truth after
  its manual bootstrap and OpenTofu import.
- `.github` and `groovemap-music.github.io` are the only expected public exceptions. Each
  needs a separate content and secret-exposure review before visibility changes.
- GitHub Pages enablement, custom-domain configuration, and DNS changes remain separate
  approval gates. They are not implied by authorization to create private repositories.
- OpenTofu plan and apply remain operator-local until CI identity, decryption, state, and
  approval controls are designed. Every complete plan must be reviewed before apply.
- Repository creation and migration work must not publish packages or releases.
- Organization-wide 2FA enforcement, base-permission changes, member repository-creation
  restrictions, billing upgrades, and display-name changes are explicit future settings
  changes; none was performed during this evidence capture.

The only external mutation completed before this baseline was manual creation of the empty
`groovemap-music` organization. No repository, team, ruleset, Pages site, DNS record, or
organization setting was created or changed by the migration.

## Source preservation and licensing boundaries

The source monorepo remains at
`/Users/Robert/workspaces/github/SimplicityGuy/discogsography`. It and its Git history must
remain intact throughout the initial split. Every destination extraction must use a
recorded, reproducible history-preserving method and be independently verified before any
separately approved source cleanup.

The approved license boundaries are:

- MIT: `python-libraries`, `catalog-ingestion`, `discogs-graph-enricher`,
  `discogs-sql-loader`, `musicbrainz-graph-enricher`, and
  `musicbrainz-sql-loader`.
- Existing PolyForm Noncommercial license: `analytics-engine` and `graph-explorer`.
- All other repositories retain the existing license until explicitly decided otherwise.

Historical license files must not be rewritten during filtering. Applicable third-party,
font, vendored-code, notice, and attribution obligations follow the content into each
destination regardless of the destination's first-party license.
