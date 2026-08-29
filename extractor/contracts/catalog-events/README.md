# Catalog event contracts

`catalog-ingestion` owns the versioned wire contract in this directory. Version `v1`
defines the event envelopes, entity vocabulary, exchange and queue naming, extraction
rules, and deterministic fixtures consumed by the Python services.

Run the generator from the repository root whenever `v1/contract.json` changes:

```bash
uv run python extractor/contracts/generate.py
```

The command writes the Rust constants, a pinned Python artifact into each current
consumer, and fixtures beneath `v1/fixtures/`. Generated files contain a provenance
header and must not be edited directly. CI verifies regeneration is byte-for-byte clean.

Contract versions describe the distribution containing an event; the v1 envelope is
kept unchanged for compatibility and therefore does not add an on-wire version field.
Breaking changes require a new sibling version directory and a coordinated producer /
consumer rollout. Additive entity fields remain compatible because data events permit
source-specific fields beyond the stable `type`, `id`, and `sha256` envelope.

The extraction policy remains `extractor/extraction-rules.yaml`; it is part of the
catalog-ingestion release and is not copied into consumers.
