# Neo4j Indexing Strategy

## Overview

This document describes the Neo4j indexing strategy for the API service to optimize query performance. Indexes are automatically created during service startup.

> 📖 For detailed analysis of how these indexes support query optimization, see the [Query Performance Optimizations](query-performance-optimizations.md) report.

## Index Types

### Full-Text Indexes

Full-text indexes enable efficient text search queries using `CONTAINS` and case-insensitive matching.

| Index Name               | Label   | Properties | Use Case                        |
| ------------------------ | ------- | ---------- | ------------------------------- |
| `artist_name_fulltext`   | Artist  | name       | Search endpoint artist queries  |
| `release_title_fulltext` | Release | title      | Search endpoint release queries |
| `label_name_fulltext`    | Label   | name       | Search endpoint label queries   |
| `genre_name_fulltext`    | Genre   | name       | Search endpoint genre queries   |
| `style_name_fulltext`    | Style   | name       | Search endpoint style queries   |

**Example Query**:

```cypher
MATCH (a:Artist)
WHERE toLower(a.name) CONTAINS toLower($query)
RETURN a.id, a.name
ORDER BY a.name
```

### Range Indexes

Range indexes enable fast lookups by exact value and support efficient sorting.

#### ID Lookups

| Index Name         | Label   | Properties | Use Case                        |
| ------------------ | ------- | ---------- | ------------------------------- |
| `artist_id_index`  | Artist  | id         | Graph traversal, artist details |
| `release_id_index` | Release | id         | Release lookups                 |
| `label_id_index`   | Label   | id         | Label lookups                   |
| `genre_id_index`   | Genre   | id         | Genre lookups                   |

**Example Query**:

```cypher
MATCH (a:Artist {id: $artist_id})
RETURN a
```

#### Sorting Indexes

| Index Name            | Label   | Properties | Use Case                               |
| --------------------- | ------- | ---------- | -------------------------------------- |
| `artist_name_index`   | Artist  | name       | Alphabetical sorting in search results |
| `release_title_index` | Release | title      | Alphabetical sorting in search results |
| `label_name_index`    | Label   | name       | Alphabetical sorting in search results |
| `genre_name_index`    | Genre   | name       | Alphabetical sorting in trends         |

**Example Query**:

```cypher
MATCH (a:Artist)
WHERE a.name CONTAINS $query
RETURN a
ORDER BY a.name
```

#### Range Queries

| Index Name               | Label   | Properties | Use Case                                         |
| ------------------------ | ------- | ---------- | ------------------------------------------------ |
| `release_year_index`     | Release | year       | Year range queries, trends, year-range min/max   |
| `master_year_index`      | Master  | year       | Monthly anniversaries (insights/this-month)      |
| `genre_first_year_index` | Genre   | first_year | Genre emergence timeline (index-backed ORDER BY) |
| `style_first_year_index` | Style   | first_year | Style emergence timeline (index-backed ORDER BY) |

**Example Query**:

```cypher
MATCH (r:Release)
WHERE r.year >= $start_year AND r.year <= $end_year
RETURN r
ORDER BY r.year
```

### Pre-Computed Aggregate Properties

In addition to indexes, several node types have pre-computed aggregate properties that are set during the graphinator post-import step (`compute_genre_style_stats()`). These replace expensive runtime traversals with simple property reads.

#### Genre Node Properties

| Property        | Description                                | Replaces                           |
| --------------- | ------------------------------------------ | ---------------------------------- |
| `release_count` | Number of releases tagged with this genre  | `COUNT { (g)<-[:IS]-(r:Release) }` |
| `artist_count`  | Number of distinct artists across releases | Traversal of IS→BY edges           |
| `label_count`   | Number of distinct labels across releases  | Traversal of IS→ON edges           |
| `style_count`   | Number of distinct styles across releases  | Traversal of IS→IS edges           |
| `first_year`    | Earliest release year in this genre        | `min(r.year)` across all releases  |

#### Style Node Properties

| Property        | Description                                |
| --------------- | ------------------------------------------ |
| `release_count` | Number of releases tagged with this style  |
| `artist_count`  | Number of distinct artists across releases |
| `label_count`   | Number of distinct labels across releases  |
| `genre_count`   | Number of distinct genres across releases  |
| `first_year`    | Earliest release year in this style        |

**Impact**: For `explore/genre/Electronic`, this reduces queries from **200M DB accesses** (traversing 5.6M releases × 4 relationship types) to **6 DB accesses** (single NodeUniqueIndexSeek + 4 property reads).

**Example Query (before):**

```cypher
-- 200M DB hits, 201MB memory for "Electronic"
MATCH (g:Genre {name: $name})
WITH g
MATCH (r:Release)-[:IS]->(g)
WITH g, collect(DISTINCT r) AS releases
-- ... 3 more OPTIONAL MATCHes
```

**Example Query (after):**

```cypher
-- 6 DB hits, 64 bytes memory
MATCH (g:Genre {name: $name})
RETURN g.name AS id, g.name AS name,
       g.release_count AS release_count,
       g.artist_count AS artist_count,
       g.label_count AS label_count,
       g.style_count AS style_count
```

## Performance Impact

### Before Indexing

- Text search queries: 500-1000ms for 10,000+ nodes
- ID lookups: 100-200ms for deep graph traversal
- Sorted results: 200-500ms for ORDER BY operations

### After Indexing

- Text search queries: 10-50ms (10-20x improvement)
- ID lookups: 1-5ms (20-100x improvement)
- Sorted results: 5-20ms (10-25x improvement)

## Index Management

### Automatic Creation

Indexes are automatically created during system startup by the **schema-init** service via `schema-init/neo4j_schema.py`. All statements use `IF NOT EXISTS`, so they are idempotent — subsequent calls are no-ops.

### Manual Management

Create all schema objects manually:

```bash
uv run python -c "
import asyncio
from schema_init.neo4j_schema import create_neo4j_schema
from common import AsyncResilientNeo4jDriver
driver = AsyncResilientNeo4jDriver('bolt://localhost:7687', auth=('neo4j', 'password'))
asyncio.run(create_neo4j_schema(driver))
"
```

List existing indexes:

```bash
# In Neo4j Browser or cypher-shell
SHOW INDEXES
```

Drop a specific index:

```bash
# In Neo4j Browser or cypher-shell
DROP INDEX index_name IF EXISTS
```

### Monitoring Index Usage

Use `EXPLAIN` or `PROFILE` to verify index usage:

```cypher
EXPLAIN MATCH (a:Artist)
WHERE toLower(a.name) CONTAINS "beatles"
RETURN a
```

Look for `NodeIndexSeek` or `NodeIndexSeekByRange` in the execution plan.

## Index Definitions

All schema objects are defined in `schema-init/neo4j_schema.py` in the `SCHEMA_STATEMENTS` list. Each entry is a `(name, cypher)` tuple where the Cypher string uses `IF NOT EXISTS` for idempotency.

## Future Optimizations

### Potential Composite Indexes

- `(Release.year, Release.title)` — if sorting by title within year ranges becomes common
- `(Artist.name, Artist.id)` — if combined filtering and sorting is needed

> **Note**: Composite indexes are only available in Neo4j Enterprise Edition.

### Pre-Computed Properties on Additional Node Types

- `Artist.release_count`, `Artist.label_count` — currently computed at query time via COUNT {} subqueries (4K-102K DB hits); could be pre-computed during import for artists with >1000 releases
- `Label.release_count`, `Label.artist_count` — already partially pre-computed; could add more aggregate dimensions

## Related Documentation

- [Database Schema](./database-schema.md)
- [Performance Guide](./performance-guide.md)
- [Query Performance Optimizations](./query-performance-optimizations.md)
