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

#### Find artist collaborations

```cypher
MATCH (a1:Artist {name: "David Bowie"})-[:COLLABORATED_WITH]-(a2:Artist)
RETURN DISTINCT a2.name as collaborator
ORDER BY collaborator;
```

#### Find collaboration network (2 degrees of separation)

```cypher
MATCH path = (a1:Artist {name: "Miles Davis"})-[:COLLABORATED_WITH*1..2]-(a2:Artist)
WHERE a1 <> a2
RETURN DISTINCT a2.name as artist, length(path) as degrees_of_separation
ORDER BY degrees_of_separation, artist
LIMIT 20;
```

#### Find artists who worked together on specific release

```cypher
MATCH (a:Artist)-[:PERFORMED_ON]->(r:Release {title: "Kind of Blue"})
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
    COLLABORATED_WITH: {
      orientation: 'UNDIRECTED'
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

## 🎵 Discovery Service Examples

The Discovery service provides AI-powered music intelligence through its REST API.

### Semantic Search

```bash
# Search for similar artists
curl "http://localhost:8005/api/similar-artists?artist=Miles%20Davis&limit=10"
```

### Genre Analysis

```bash
# Get genre trends over time
curl "http://localhost:8005/api/genre-trends?genre=Jazz&start_year=1950&end_year=1970"
```

### Artist Network

```bash
# Get artist collaboration network
curl "http://localhost:8005/api/artist-network?artist=David%20Bowie&depth=2"
```

### Label Analytics

```bash
# Get label statistics
curl "http://localhost:8005/api/label-stats?label=Blue%20Note"
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

2. **Neo4j**: Explore collaborations on those releases

```cypher
MATCH (a:Artist)-[:PERFORMED_ON]->(r:Release {title: "Kind of Blue"})
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

**Last Updated**: 2025-01-15
