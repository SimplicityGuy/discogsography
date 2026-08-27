# Persistence contracts

`database-schema` owns Neo4j and PostgreSQL compatibility. Versioned metadata in
`persistence/` defines the policy; the executable schema sources remain the Python files
listed by each version.

Additive changes may remain within a contract version. Renames, removals, type changes,
constraint changes, or changed relationship semantics require an explicit migration and
major contract version. Use expand/migrate/contract ordering so independently deployed
services never require lockstep source checkouts.

Catalog event shape is not owned here. It belongs to `catalog-ingestion`; API shape belongs
to `catalog-api`.
