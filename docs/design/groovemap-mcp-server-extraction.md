# GrooveMap MCP server extraction evidence

The private `groovemap-music/mcp-server` repository was extracted from this
monorepo without modifying or deleting source content here.

## History extraction

The extraction used an isolated, non-local clone of this bead branch and
`git-filter-repo`:

```bash
git clone --no-local --single-branch --no-tags \
  --branch wt/bead/issue/discogsography-2kpm.22 \
  /Users/Robert/workspaces/github/SimplicityGuy/discogsography mcp-server
git filter-repo --force \
  --path mcp-server/ --path-rename mcp-server/: \
  --path tests/mcp-server/ --path-rename tests/mcp-server/:tests/ \
  --path LICENSE \
  --path docs/superpowers/plans/2026-03-14-mcp-server.md \
  --path docs/superpowers/specs/2026-03-25-natural-language-graph-queries-design.md \
  --path docs/superpowers/specs/2026-04-14-ask-mode-integration-design.md \
  --path docs/architecture.md \
  --path docs/configuration.md \
  --path docs/development.md
```

The filtered branch retained 106 source commits. The standalone establishment
commit is `aedee6228c8908060ee735db02463c2325a5a6f7`, producing 107 commits on the
destination `main` branch. Historical license states remain in retained
history; current destination source is MIT-licensed by owner decision.

## Dependency boundaries

- The MCP server has no database access and does not import Catalog API
  implementation modules.
- `groovemap-agent-tools==0.1.0` and `groovemap-runtime==0.1.0` resolve from
  immutable `python-libraries` commit
  `28fa329702bc76896cc54ab8d05ec5b1bd3d929e`.
- Catalog API commit `ad7bd13252eb3483d47bce6680e651475d233bfe`
  owns the v1 MCP route contract. Its producer CI run `33116492912` passed.
- The destination promotes that contract with its SHA-256 digest and checks all
  route literals and the 12-tool MCP protocol surface locally.

## Verification

The following destination checks passed before push:

- `just check`: formatting, linting, history/tree secret scans, mypy, 47 tests
  at 96% line coverage, protocol/API contract tests, wheel/sdist build, clean
  wheel installation, dependency-license policy, and Commitizen preview.
- `just audit`: no known vulnerabilities in auditable dependencies; the three
  private GrooveMap distributions are not present on PyPI and were explicitly
  reported as unaudited by `pip-audit`.
- `just release-dry-run`: wheel/sdist, checksums, CycloneDX SBOM, third-party
  notices, and build provenance generated without publishing.
- `gitleaks git --redact --no-banner` and
  `gitleaks dir . --redact --no-banner`: no leaks found.

The repository remains private. Publishing and hosted release automation are
disabled until a short-lived private-repository read identity and publishing
authority are approved. Destination Source CI run `33117039555` passed for the
establishment commit.
