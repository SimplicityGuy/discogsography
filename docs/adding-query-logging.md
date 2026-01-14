# Adding Neo4j Query Logging to Discovery Service

This document describes how to add DEBUG-level logging for Neo4j queries in the discovery service.

## Overview

When `LOG_LEVEL=DEBUG`, all Neo4j queries should be logged with their parameters to aid in debugging and performance analysis.

## Pattern to Follow

### Before (without logging):

```python
async with self.driver.session() as session:
    result = await session.run(
        """
        MATCH (n:Artist)
        WHERE n.name CONTAINS $search
        RETURN n
        LIMIT $limit
        """,
        search=search_term,
        limit=limit,
    )
```

### After (with logging):

```python
async with self.driver.session() as session:
    query = """
        MATCH (n:Artist)
        WHERE n.name CONTAINS $search
        RETURN n
        LIMIT $limit
        """
    params = {"search": search_term, "limit": limit}
    logger.debug("🔍 Executing Neo4j query", query=query.strip(), params=params)

    result = await session.run(query, **params)
```

## Steps to Add Logging

1. **Extract the query string** to a variable named `query`
2. **Extract parameters** to a dictionary named `params`
3. **Add logger.debug()** statement with query and params
4. **Update session.run()** to use the query variable and **params

## Files Completed

✅ `discovery/graph_explorer.py` - 6 queries logged
✅ `discovery/recommender.py` - 4 queries logged

## Files Remaining

The following files need query logging added:

| File | Query Count | Priority |
|------|-------------|----------|
| `playground_api.py` | 10 | High (main API) |
| `analytics.py` | 7 | High (analytics engine) |
| `genre_evolution.py` | 6 | Medium |
| `similarity_network.py` | 5 | Medium |
| `collaborative_filtering.py` | 3 | Medium |
| `trend_tracking.py` | 3 | Low |
| `community_detection.py` | 2 | Low |
| `content_based.py` | 1 | Low |
| `centrality_metrics.py` | 1 | Low |

Total: 38 queries remaining

## Special Cases

### F-String Queries

If the query uses f-strings for dynamic construction:

```python
# Before
genre_filter = ""
if genres:
    genre_filter = "AND any(g IN genres WHERE g IN $genres)"

result = await session.run(
    f"""
    MATCH (a:Artist)
    WHERE condition {genre_filter}
    RETURN a
    """,
    genres=genres,
)

# After
genre_filter = ""
if genres:
    genre_filter = "AND any(g IN genres WHERE g IN $genres)"

query = f"""
    MATCH (a:Artist)
    WHERE condition {genre_filter}
    RETURN a
    """
params = {"genres": genres}
logger.debug("🔍 Executing Neo4j query", query=query.strip(), params=params)

result = await session.run(query, **params)
```

### Queries Without Parameters

If there are no parameters:

```python
# Before
result = await session.run("""
    MATCH (n)
    RETURN count(n) as total
    """)

# After
query = """
    MATCH (n)
    RETURN count(n) as total
    """
logger.debug("🔍 Executing Neo4j query", query=query.strip())

result = await session.run(query)
```

## Testing

To test query logging:

```bash
# Set LOG_LEVEL to DEBUG
export LOG_LEVEL=DEBUG

# Run discovery service
uv run python discovery/discovery.py

# Or with Docker
docker-compose up discovery

# Check logs for query output
docker logs -f discogsography-discovery | grep "Executing Neo4j query"
```

### Expected Log Output

```json
{
  "timestamp": "2026-01-13T20:00:00.123456Z",
  "level": "debug",
  "logger": "discovery.graph_explorer",
  "event": "🔍 Executing Neo4j query",
  "query": "MATCH (n) WHERE n.name CONTAINS $search RETURN n LIMIT $limit",
  "params": {"search": "Beatles", "limit": 20},
  "service": "discovery"
}
```

## Benefits

- **Debugging**: See exactly what queries are being executed
- **Performance**: Identify slow or inefficient queries
- **Development**: Understand query patterns and optimize them
- **Troubleshooting**: Diagnose issues with query parameters

## Guidelines

1. **Always use the 🔍 emoji** for consistency with logging standards
2. **Strip whitespace** from queries with `.strip()` for cleaner logs
3. **Include all parameters** in the params dict for complete context
4. **Don't log query results** - only the query and parameters
5. **Use DEBUG level** - these logs should only appear when explicitly enabled

## See Also

- [Emoji Guide](emoji-guide.md) - Standard emoji usage
- [Logging Configuration](logging-configuration.md) - LOG_LEVEL setup
- [Discovery README](../discovery/README.md) - Service documentation
