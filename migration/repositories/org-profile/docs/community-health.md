# Community-health inheritance

GitHub can use specific files from a public organization `.github` repository as defaults
for repositories that do not define their own versions. That inheritance can change the
public contribution or support contract of every repository in the organization.

This initial tree deliberately enables none of those shared files. In particular, it does
not contain a shared code of conduct, contributing guide, funding configuration,
governance policy, security policy, support policy, issue templates, or pull-request
template. [`policy/community-health.json`](../policy/community-health.json) records that
empty allowlist, and validation rejects an inherited file that is not declared there.

Before adding a shared file:

1. verify the current GitHub-supported filename and inheritance behavior;
2. decide whether every repository lacking a local override should inherit it;
3. review its public disclosure, contact information, and licensing implications;
4. add the path and behavior to the policy manifest; and
5. test inheritance in a disposable private repository before public rollout.

`profile/README.md` is not a community-health default. GitHub uses it only as the
organization profile when this repository is public.
