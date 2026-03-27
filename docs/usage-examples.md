# 💡 Usage Examples

<div align="center">

**Practical query examples for Neo4j and PostgreSQL**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [🗄️ Database Schema](database-schema.md)

</div>

## Overview

Once your data is loaded, explore the music universe through powerful queries and AI-driven insights. This guide provides practical examples for both Neo4j graph queries and PostgreSQL analytics.

## 🔗 Neo4j Graph Queries

Neo4j excels at exploring complex relationships in the music industry. Use Cypher query language to navigate connections between artists, releases, labels, and genres.

### Artist Queries

#### Find all albums by an artist

```cypher
MATCH (a:Artist {name: "Pink Floyd"})-[:BY]-(r:Release)
RETURN r.title, r.year
ORDER BY r.year
LIMIT 10;
```

#### Get artist discography with labels

```cypher
MATCH (a:Artist {name: "Miles Davis"})-[:BY]-(r:Release)-[:ON]->(l:Label)
RETURN r.title, r.year, l.name as label
ORDER BY r.year;
```

#### Find artist aliases

```cypher
MATCH (alias:Artist)-[:ALIAS_OF]->(primary:Artist {name: "Prince"})
RETURN alias.name as alias_name, primary.name as primary_name;
```

#### Discover band members

```cypher
MATCH (member:Artist)-[:MEMBER_OF]->(band:Artist {name: "The Beatles"})
RETURN member.name, member.real_name
ORDER BY member.name;
```

#### Find all groups an artist belongs to

```cypher
MATCH (artist:Artist {name: "Eric Clapton"})-[:MEMBER_OF]->(band:Artist)
RETURN band.name as band_name
ORDER BY band_name;
```

### Collaboration Queries

#### Find artists who share releases (implicit collaborations)

```cypher
MATCH (a1:Artist {name: "David Bowie"})<-[:BY]-(r:Release)-[:BY]->(a2:Artist)
WHERE a1 <> a2
RETURN DISTINCT a2.name as collaborator, count(r) as shared_releases
ORDER BY shared_releases DESC;
```

#### Find collaboration network (2 degrees of separation)

```cypher
MATCH path = (a1:Artist {name: "Miles Davis"})<-[:BY]-(r1:Release)-[:BY]->(a2:Artist)<-[:BY]-(r2:Release)-[:BY]->(a3:Artist)
WHERE a1 <> a2 AND a1 <> a3 AND a2 <> a3
RETURN DISTINCT a3.name as artist, 2 as degrees_of_separation
ORDER BY artist
LIMIT 20;
```

#### Find artists who worked together on a specific release

```cypher
MATCH (a:Artist)<-[:BY]-(r:Release {title: "Kind of Blue"})
RETURN a.name as artist, r.title as release
ORDER BY artist;
```

### Label Queries

#### Explore label catalog

```cypher
MATCH (r:Release)-[:ON]->(l:Label {name: "Blue Note"})
WHERE r.year >= 1950 AND r.year <= 1970
RETURN r.title, r.year
ORDER BY r.year
LIMIT 20;
```

#### Find sublabels of a parent label

```cypher
MATCH (sublabel:Label)-[:SUBLABEL_OF]->(parent:Label {name: "EMI"})
RETURN sublabel.name as sublabel
ORDER BY sublabel;
```

#### Find label hierarchy

```cypher
MATCH path = (sublabel:Label)-[:SUBLABEL_OF*]->(parent:Label {name: "Universal Music Group"})
RETURN sublabel.name as label, length(path) as levels_deep
ORDER BY levels_deep, label;
```

#### Count releases per label

```cypher
MATCH (r:Release)-[:ON]->(l:Label)
WITH l.name as label, count(r) as release_count
RETURN label, release_count
ORDER BY release_count DESC
LIMIT 20;
```

### Genre and Style Queries

#### Find releases by genre

```cypher
MATCH (r:Release)-[:IS]->(g:Genre {name: "Jazz"})
RETURN r.title, r.year
ORDER BY r.year DESC
LIMIT 20;
```

#### Find releases by style

```cypher
MATCH (r:Release)-[:IS]->(s:Style {name: "Progressive Rock"})
RETURN r.title, r.year
ORDER BY r.year
LIMIT 20;
```

#### Analyze genre connections

```cypher
MATCH (r:Release)-[:IS]->(g:Genre)
WITH g.name as genre, count(r) as release_count
RETURN genre, release_count
ORDER BY release_count DESC
LIMIT 20;
```

#### Find style-to-genre relationships

```cypher
MATCH (s:Style)-[:PART_OF]->(g:Genre)
RETURN g.name as genre, collect(s.name) as styles
ORDER BY genre;
```

#### Find releases with multiple genres

```cypher
MATCH (r:Release)-[:IS]->(g:Genre)
WITH r, collect(g.name) as genres
WHERE size(genres) > 1
RETURN r.title, r.year, genres
ORDER BY r.year DESC
LIMIT 20;
```

### Master and Release Queries

#### Find all releases of a master

```cypher
MATCH (r:Release)-[:DERIVED_FROM]->(m:Master {title: "Dark Side of the Moon"})
RETURN r.title, r.year, r.country, r.format
ORDER BY r.year;
```

#### Find main release of a master

```cypher
MATCH (m:Master {title: "Kind of Blue"})<-[:DERIVED_FROM]-(r:Release)
WHERE r.id = m.main_release
RETURN r.title, r.year, r.country;
```

#### Count releases per country for a master

```cypher
MATCH (m:Master {title: "Abbey Road"})<-[:DERIVED_FROM]-(r:Release)
WITH r.country as country, count(r) as release_count
RETURN country, release_count
ORDER BY release_count DESC;
```

### Advanced Queries

#### Find most prolific artists by release count

```cypher
MATCH (a:Artist)-[:BY]-(r:Release)
WITH a.name as artist, count(r) as release_count
RETURN artist, release_count
ORDER BY release_count DESC
LIMIT 20;
```

#### Find releases from a specific year and genre

```cypher
MATCH (r:Release)-[:IS]->(g:Genre {name: "Jazz"})
WHERE r.year = 1959
RETURN r.title, r.country
ORDER BY r.title;
```

#### Find artists active in multiple genres

```cypher
MATCH (a:Artist)-[:BY]-(r:Release)-[:IS]->(g:Genre)
WITH a.name as artist, collect(DISTINCT g.name) as genres
WHERE size(genres) > 3
RETURN artist, genres
ORDER BY size(genres) DESC
LIMIT 20;
```

#### PageRank - Find influential artists

```cypher
CALL gds.pageRank.stream({
  nodeProjection: 'Artist',
  relationshipProjection: {
    BY: {
      orientation: 'REVERSE'
    }
  }
})
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS artist, score
ORDER BY score DESC
LIMIT 20;
```

## 🐘 PostgreSQL Queries

PostgreSQL provides fast structured queries and full-text search capabilities on denormalized JSONB data.

### Artist Queries

#### Search artists by name

```sql
SELECT
    data->>'name' as name,
    data->>'real_name' as real_name,
    data->>'profile' as profile
FROM artists
WHERE data->>'name' ILIKE '%pink%floyd%'
LIMIT 10;
```

#### Get artist with all details

```sql
SELECT data
FROM artists
WHERE data->>'name' = 'Miles Davis';
```

#### Find artists by real name

```sql
SELECT
    data->>'name' as artist_name,
    data->>'real_name' as real_name
FROM artists
WHERE data->>'real_name' IS NOT NULL
AND data->>'real_name' != ''
ORDER BY data->>'name'
LIMIT 20;
```

### Release Queries

#### Full-text search releases

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year,
    data->'artists' as artists
FROM releases
WHERE data->>'title' ILIKE '%dark side%'
ORDER BY (data->>'year')::int DESC
LIMIT 10;
```

#### Artist discography

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year,
    data->'genres' as genres
FROM releases
WHERE data @> '{"artists": [{"name": "Miles Davis"}]}'
AND (data->>'year')::int BETWEEN 1950 AND 1960
ORDER BY (data->>'year')::int;
```

#### Releases by year

```sql
SELECT
    data->>'title' as title,
    data->>'country' as country,
    data->'format' as format
FROM releases
WHERE (data->>'year')::int = 1969
ORDER BY data->>'title'
LIMIT 20;
```

#### Releases by country

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year
FROM releases
WHERE data->>'country' = 'UK'
AND (data->>'year')::int BETWEEN 1960 AND 1969
ORDER BY (data->>'year')::int, data->>'title'
LIMIT 20;
```

### Label Queries

#### Find releases by label

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year
FROM releases
WHERE data @> '{"labels": [{"name": "Blue Note"}]}'
ORDER BY (data->>'year')::int
LIMIT 20;
```

#### Get label details

```sql
SELECT data
FROM labels
WHERE data->>'name' = 'Blue Note';
```

#### Find labels with sublabels

```sql
SELECT
    data->>'name' as label,
    data->'sublabels' as sublabels
FROM labels
WHERE data->'sublabels' IS NOT NULL
AND jsonb_array_length(data->'sublabels') > 0
LIMIT 20;
```

### Genre and Statistics Queries

#### Genre statistics

```sql
SELECT
    genre,
    COUNT(*) as release_count,
    MIN((data->>'year')::int) as first_release,
    MAX((data->>'year')::int) as last_release
FROM releases,
     jsonb_array_elements_text(data->'genres') as genre
GROUP BY genre
ORDER BY release_count DESC
LIMIT 20;
```

#### Style statistics

```sql
SELECT
    style,
    COUNT(*) as release_count
FROM releases,
     jsonb_array_elements_text(data->'styles') as style
GROUP BY style
ORDER BY release_count DESC
LIMIT 20;
```

#### Releases by year (aggregate)

```sql
SELECT
    data->>'year' as year,
    COUNT(*) as release_count
FROM releases
WHERE data->>'year' IS NOT NULL
GROUP BY data->>'year'
ORDER BY year DESC
LIMIT 20;
```

#### Country statistics

```sql
SELECT
    data->>'country' as country,
    COUNT(*) as release_count
FROM releases
WHERE data->>'country' IS NOT NULL
GROUP BY data->>'country'
ORDER BY release_count DESC
LIMIT 20;
```

### Advanced JSONB Queries

#### Search by label and catalog number

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year,
    label->>'name' as label,
    label->>'catno' as catalog_number
FROM releases,
     jsonb_array_elements(data->'labels') as label
WHERE (data->>'year')::int = 1959
AND label->>'name' = 'Columbia'
ORDER BY data->>'title';
```

#### Find releases with specific format

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year,
    data->'format' as format
FROM releases
WHERE data->'format' @> '["Vinyl"]'
AND (data->>'year')::int >= 1960
ORDER BY (data->>'year')::int
LIMIT 20;
```

#### Complex multi-condition query

```sql
SELECT
    data->>'title' as title,
    data->>'year' as year,
    data->'genres' as genres,
    data->'artists' as artists
FROM releases
WHERE data @> '{"genres": ["Jazz"]}'
AND (data->>'year')::int BETWEEN 1955 AND 1965
AND data->>'country' = 'US'
ORDER BY (data->>'year')::int, data->>'title'
LIMIT 20;
```

#### Tracklist analysis

```sql
SELECT
    data->>'title' as album,
    data->>'year' as year,
    jsonb_array_length(data->'tracklist') as track_count
FROM releases
WHERE data->'tracklist' IS NOT NULL
ORDER BY track_count DESC
LIMIT 20;
```

### Performance Queries

#### Count records by table

```sql
SELECT 'artists' as table_name, COUNT(*) FROM artists
UNION ALL
SELECT 'labels', COUNT(*) FROM labels
UNION ALL
SELECT 'releases', COUNT(*) FROM releases
UNION ALL
SELECT 'masters', COUNT(*) FROM masters;
```

#### Table sizes

```sql
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) -
                   pg_relation_size(schemaname||'.'||tablename)) AS index_size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

## 🔐 API Service Examples

The API service provides graph exploration endpoints at `http://localhost:8004`.

### Graph Exploration

```bash
# Search with autocomplete (artist, genre, label, or style)
curl "http://localhost:8004/api/autocomplete?q=miles&type=artist&limit=10"

# Explore a center node (returns categories with counts)
curl "http://localhost:8004/api/explore?name=Miles%20Davis&type=artist"

# Expand a category (paginated)
curl "http://localhost:8004/api/expand?node_id=Miles%20Davis&type=artist&category=releases&limit=50&offset=0"

# Get full details for a node
curl "http://localhost:8004/api/node/1?type=artist"
```

### Trend Analysis

```bash
# Get year-by-year release counts for an entity
curl "http://localhost:8004/api/trends?name=Miles%20Davis&type=artist"
curl "http://localhost:8004/api/trends?name=Jazz&type=genre"
curl "http://localhost:8004/api/trends?name=Blue%20Note&type=label"
```

### User Collection (requires JWT authentication)

```bash
# Register a user account
curl -X POST "http://localhost:8004/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret"}'

# Login to receive a JWT token
curl -X POST "http://localhost:8004/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret"}'

# Use the token to query your collection
curl "http://localhost:8004/api/user/collection?limit=50" \
  -H "Authorization: Bearer <your-jwt-token>"

# Get collection statistics
curl "http://localhost:8004/api/user/collection/stats" \
  -H "Authorization: Bearer <your-jwt-token>"

# Get recommendations based on your collection
curl "http://localhost:8004/api/user/recommendations?limit=20" \
  -H "Authorization: Bearer <your-jwt-token>"
```

### Graph Snapshots

Snapshots are persisted in Redis with a configurable TTL (default 28 days) and survive service restarts.

```bash
# Save a graph snapshot (requires authentication)
curl -X POST "http://localhost:8004/api/snapshot" \
  -H "Authorization: Bearer <your-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "nodes": [{"id": "1", "type": "artist"}, {"id": "2", "type": "release"}],
    "center": {"id": "1", "type": "artist"}
  }'
# Response: {"token": "<token>", "url": "/snapshot/<token>", "expires_at": "<iso-datetime>"}

# Restore a saved snapshot (public, no auth required)
curl "http://localhost:8004/api/snapshot/<token>"
```

### Unified Search

```bash
# Full-text search across all entity types
curl "http://localhost:8004/api/search?q=kraftwerk&types=artist&limit=10"

# Search releases with genre and year filters
curl "http://localhost:8004/api/search?q=blue&types=release&genres=Jazz&year_min=1955&year_max=1965&limit=20"

# Search across multiple entity types with pagination
curl "http://localhost:8004/api/search?q=warp&types=artist,label&limit=10&offset=0"
```

### Path Finder

```bash
# Find the shortest path between two artists
curl "http://localhost:8004/api/path?from_name=Miles%20Davis&from_type=artist&to_name=John%20Coltrane&to_type=artist"

# Find the shortest path between an artist and a label
curl "http://localhost:8004/api/path?from_name=Kraftwerk&from_type=artist&to_name=Mute&to_type=label&max_depth=8"

# Cross-type path between a genre and a label
curl "http://localhost:8004/api/path?from_name=Techno&from_type=genre&to_name=Warp%20Records&to_type=label"
```

### Vinyl Archaeology (Time Travel)

```bash
# Get the year range of all releases in the database
curl "http://localhost:8004/api/explore/year-range"

# Discover which genres had emerged before a given year
curl "http://localhost:8004/api/explore/genre-emergence?before_year=1980"

# Browse releases for a genre filtered to before a specific year
curl "http://localhost:8004/api/expand?node_id=Electronic&type=genre&category=releases&before_year=1985&limit=50&offset=0"
```

### Insights (Precomputed Analytics)

```bash
# Top artists by release count
curl "http://localhost:8004/api/insights/top-artists"

# Genre trends over time (filter by genre)
curl "http://localhost:8004/api/insights/genre-trends?genre=Electronic"

# Label longevity — longest-running labels
curl "http://localhost:8004/api/insights/label-longevity"

# Releases and milestones from this month in history
curl "http://localhost:8004/api/insights/this-month"

# Data completeness report across all entity types
curl "http://localhost:8004/api/insights/data-completeness"

# Computation status of precomputed insights
curl "http://localhost:8004/api/insights/status"
```

### Label DNA (Fingerprint and Compare)

```bash
# Get the full DNA fingerprint for a label (genres, styles, decades, formats)
curl "http://localhost:8004/api/label/12345/dna"

# Find labels with a similar DNA fingerprint
curl "http://localhost:8004/api/label/12345/similar?limit=10"

# Side-by-side DNA comparison of multiple labels (2-5 IDs)
curl "http://localhost:8004/api/label/dna/compare?ids=12345,67890,11111"
```

### Taste Fingerprint (requires JWT authentication)

```bash
# Genre x decade heatmap of your collection
curl "http://localhost:8004/api/user/taste/heatmap" \
  -H "Authorization: Bearer <your-jwt-token>"

# Full taste fingerprint (heatmap, obscurity score, drift, blind spots)
curl "http://localhost:8004/api/user/taste/fingerprint" \
  -H "Authorization: Bearer <your-jwt-token>"

# Genres your favourite artists release in but you haven't collected
curl "http://localhost:8004/api/user/taste/blindspots?limit=10" \
  -H "Authorization: Bearer <your-jwt-token>"

# Shareable SVG taste card
curl "http://localhost:8004/api/user/taste/card" \
  -H "Authorization: Bearer <your-jwt-token>" \
  -o taste-card.svg
```

### Collaboration Network

```bash
# Find multi-hop collaborators (artists connected via shared releases)
curl "http://localhost:8004/api/network/artist/123/collaborators?depth=2&limit=50"

# Get centrality scores for an artist (degree, collaborator count, group/alias)
curl "http://localhost:8004/api/network/artist/123/centrality"

# Detect community clusters around an artist (grouped by primary genre)
curl "http://localhost:8004/api/network/cluster/123?limit=50"
```

### Collection Timeline and Evolution (requires JWT authentication)

```bash
# Collection timeline bucketed by year
curl "http://localhost:8004/api/user/collection/timeline?bucket=year" \
  -H "Authorization: Bearer <your-jwt-token>"

# Collection timeline bucketed by decade
curl "http://localhost:8004/api/user/collection/timeline?bucket=decade" \
  -H "Authorization: Bearer <your-jwt-token>"

# Collection evolution by genre over time
curl "http://localhost:8004/api/user/collection/evolution?metric=genre" \
  -H "Authorization: Bearer <your-jwt-token>"

# Collection evolution by style over time
curl "http://localhost:8004/api/user/collection/evolution?metric=style" \
  -H "Authorization: Bearer <your-jwt-token>"

# Collection evolution by label over time
curl "http://localhost:8004/api/user/collection/evolution?metric=label" \
  -H "Authorization: Bearer <your-jwt-token>"
```

## 📊 Combining Neo4j and PostgreSQL

For best results, use both databases together:

**Neo4j**: Graph relationships and algorithms
**PostgreSQL**: Fast filtering and aggregation

### Example Workflow

1. **PostgreSQL**: Find releases by year and genre

```sql
SELECT data->>'title', data->'artists'
FROM releases
WHERE data @> '{"genres": ["Jazz"]}'
AND (data->>'year')::int = 1959;
```

2. **Neo4j**: Explore artists on those releases

```cypher
MATCH (a:Artist)<-[:BY]-(r:Release {title: "Kind of Blue"})
RETURN a.name, r.title;
```

3. **PostgreSQL**: Get detailed release information

```sql
SELECT data
FROM releases
WHERE data->>'title' = 'Kind of Blue'
AND (data->>'year')::int = 1959;
```

## 🔍 Query Optimization Tips

### Neo4j Best Practices

- Use `LIMIT` to restrict result size
- Index frequently queried properties
- Use parameters for repeated queries
- Profile queries with `PROFILE` or `EXPLAIN`
- Avoid Cartesian products

### PostgreSQL Best Practices

- Use `->` for key access (returns JSONB)
- Use `->>` for text values (returns text)
- Cast explicitly: `(data->>'year')::int`
- Utilize GIN indexes: `@>` operator
- Use `EXPLAIN ANALYZE` to check query plans

## Related Documentation

- [Database Schema](database-schema.md) - Complete schema reference
- [Architecture Overview](architecture.md) - System architecture
- [Quick Start Guide](quick-start.md) - Getting started
- [Performance Guide](performance-guide.md) - Query optimization

______________________________________________________________________

**Last Updated**: 2026-03-14
