# Repository contract boundaries

This design removes monorepo-relative source knowledge from the future repository seams.
No separate data-contracts repository is introduced.

## Ownership

| Contract | Owner | Consumer mechanism |
| --- | --- | --- |
| Catalog events, entity vocabulary, exchange/queue names, extraction rules, fixtures | `catalog-ingestion` | Versioned contract release and generated, pinned Rust/Python artifacts |
| Neo4j/PostgreSQL compatibility | `database-schema` | Versioned persistence policy and migrations |
| Public and internal HTTP/OpenAPI | `catalog-api` | Versioned OpenAPI plus generated, pinned client constants |

Generated files carry their source path and must not be edited. During extraction, each
consumer keeps its generated artifact and records the corresponding producer contract
version in its dependency/lock metadata. A generator check proves that the preserved
monorepo is still reproducible; after the split, generation uses the explicitly fetched
and checksummed contract release rather than a relative sibling checkout.

## Compatibility

Catalog event v1 preserves the current wire envelope. Additive entity fields are allowed;
removing or renaming an event, entity, required envelope field, or naming component creates
a new major contract. Consumers must accept both versions during a breaking rollout.

The API owns its generated OpenAPI. The internal Insights subset is committed separately so
`analytics-engine` does not import Catalog API source. Persistence follows
expand/migrate/contract ordering and never treats a wire schema as a database schema.

## Cross-source tests

Repository-local tests may consume committed fixtures or generated artifacts, but may not
import a sibling repository's source. The migration inventory in
`tests/repository-ownership.toml` assigns mixed and whole-stack tests to `deployment` or
their actual owner. Those tests move with their assigned repository during extraction;
they are not copied into every destination.
