# Private Python package authentication

The extracted service repositories will consume tagged releases from the private
`groovemap-music/python-libraries` repository. Dependency declarations identify a tag;
`uv.lock` records the resolved immutable commit. Never place a token, password, or GitHub
App private key in the URL.

## Local development

Use GitHub CLI's credential helper so Git asks `gh` for the active account at execution
time:

```bash
gh auth status
gh auth setup-git
uv sync --frozen
```

An editable workspace/path source is permitted only in a local development override. It
must not be committed to a service's release manifest, CI configuration, or production
container build.

## GitHub Actions

Cross-repository access uses a narrowly installed GitHub App. Mint a short-lived token
with `actions/create-github-app-token` and expose it only to a credential-helper step.
Store the App identifier as a variable and its private key as an Actions secret. Do not
rewrite dependency URLs with the token, echo it, persist generated credential files, or
upload them as artifacts. Remove the helper and token-bearing environment before later
untrusted steps.

The built-in `GITHUB_TOKEN` is repository-scoped and must not be presented as granting
access to `python-libraries`. A PAT is not the default cross-repository design.

## Container builds

Use BuildKit SSH forwarding with a read-only deploy key or an ephemeral GitHub App token
through a secret mount. The Dockerfile consumes the credential in the same `RUN` layer
that performs `uv sync --frozen` and removes temporary helper state before that layer
finishes. Credentials must never enter `ARG`, `ENV`, build contexts, cache keys, labels,
remote URLs, copied files, or final image layers.

CI and image publication remain disabled until the GitHub App installation, secret scope,
workflow permissions, and cache behavior receive a separate security review.
