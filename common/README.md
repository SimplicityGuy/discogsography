# GrooveMap Python libraries

This directory is the source boundary for `groovemap-music/python-libraries`. It owns two
MIT-licensed, independently buildable distributions with synchronized initial version
`0.1.0`:

| Distribution | Import surface | Responsibility |
| --- | --- | --- |
| `groovemap-runtime` | `src/common` → `common` | Health, logging, normalization, retries, and database/message-broker resilience |
| `groovemap-agent-tools` | `agent-tools/src/common/agent_tools` → `common.agent_tools` | Framework-neutral query-tool orchestration for the catalog API and MCP server |

The runtime package uses lazy public exports so installing its base does not import
database or RabbitMQ drivers. Consumers select only `neo4j`, `postgres`, and/or
`rabbitmq` extras and pin the shared package version. During the preserved-monorepo phase,
uv resolves those names to workspace projects; extracted repositories replace that
workspace source with an immutable private Git tag and commit recorded in `uv.lock`.

Service configuration is not a library concern. Each service owns its dataclass and
defaults, while `src/common/config.py` retains only reusable parsing, secret-file, URL, TLS, pool
budget, and logging primitives. Discogs OAuth signing belongs to `catalog-api`. Extraction
state belongs to the Rust `catalog-ingestion` implementation; the unused Python duplicate
was removed while its history remains recoverable from Git.

Build both distributions independently:

```bash
uv build --project common
uv build --project common/agent-tools
```

See [private-package-auth.md](private-package-auth.md) for credential-safe local, CI, and
container installation. Tokens and credentials never belong in manifests, lockfiles,
dependency URLs, Docker arguments, or image layers.
