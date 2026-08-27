# Catalog API contracts

`catalog-api` owns the HTTP and OpenAPI contracts in this directory. The internal
Insights surface is versioned separately because `analytics-engine` is an independent
release unit. Generate its pinned consumer constants with:

```bash
uv run python api/contracts/generate.py
```

Breaking path or envelope changes require a new contract version and a coordinated
rollout. Authentication material is deliberately absent: the contract states shape,
not deployment secrets.
