# Canonical release label/catalog pairs

Graphinator release ingestion and curator collection/wantlist sync persist the
name and catalog number from the **same first label object**. The HTTP collection
and wantlist fields remain `label` and `catalog_number`. ON relationship order
cannot select or change this pair.

A first object with a nonempty string name or catalog number is usable. It writes
both `canonical_label` and `catalog_number`, explicitly clearing a missing
counterpart. An absent, empty, or unusable first object preserves an existing
pair; it never selects a later label. PostgreSQL collection `label` and JSONB
metadata follow the same rule in one upsert, preserving unrelated metadata.

Internal `canonical_pair_source = first-label` identifies usable provenance.
`canonical_pair_version = 1` records inspection, including an unusable source.
These markers are persisted in Neo4j and PostgreSQL metadata, not added to the
HTTP contract. No relationship or per-user historical label is treated as
release-level provenance. A legacy release without usable provenance returns
unknown (`null`) for both HTTP fields rather than an invented mixed pair.

## Backfill

Replay the normal release feed after deploying both writers. Graphinator bypasses
its unchanged-hash shortcut once when a release lacks its own current
`canonical_pair_ingest_version` checkpoint,
so unchanged legacy releases acquire provenance from their original first-label
source. This is a reingest strategy, not an immediate database-wide migration.
Curator inspection cannot suppress original-feed backfill.
Sources without usable first-label metadata are marked inspected while retaining
stored values; their unknown HTTP pair stays unknown until a usable later source
arrives. Subsequent unchanged messages skip normally. Changed source messages
continue to update provenance and the paired values together.

## Real database controls

`tests/integration/test_canonical_pairs.py` uses explicitly owned disposable
Neo4j and PostgreSQL servers (`DGS_PAIRS_ISOLATED=1`, `DGS_PAIRS_NEO4J_URI`,
`DGS_PAIRS_NEO4J_PASSWORD`, `DGS_PAIRS_POSTGRES_DSN`) and a fresh child PostgreSQL
database per case. Run with `just test-canonical-pairs-integration`. The Build workflow invokes
the dedicated Test job with its own disposable PostgreSQL and Neo4j services.
This job runs all 14 controls serially; ordinary API unit collection excludes
them by directory, not by weakening their isolation guards. It proves
unchanged-hash replay, reversed relationships through authenticated HTTP,
partial/non-wipe behavior in both writers, wantlist parity, and a rejected SQL
write retaining the old pair in both stores.
