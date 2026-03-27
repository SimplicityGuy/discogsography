#!/usr/bin/env bash
# compute-label-stats.sh
#
# One-time migration: pre-computes release_count, artist_count, and
# genre_count properties on all Label nodes in Neo4j.
#
# Background: the explore/label API endpoint previously traversed all of
# a label's releases on every request (1.2M DB hits for Reprise Records
# with 55K releases). After this migration, the endpoint reads pre-computed
# properties directly (~3 DB hits). New data imports will compute these
# stats automatically via graphinator's compute_genre_style_stats().
#
# Usage:
#   ./scripts/compute-label-stats.sh
#   NEO4J_CONTAINER=my-neo4j NEO4J_PASSWORD=secret ./scripts/compute-label-stats.sh
#
# Environment variables (all optional, defaults shown):
#   NEO4J_CONTAINER  docker container name  (default: discogsography-neo4j)
#   NEO4J_USER       Neo4j username          (default: neo4j)
#   NEO4J_PASSWORD   Neo4j password          (default: discogsography)

set -euo pipefail

CONTAINER="${NEO4J_CONTAINER:-discogsography-neo4j}"
USER="${NEO4J_USER:-neo4j}"
PASSWORD="${NEO4J_PASSWORD:-discogsography}"

echo "🔍 Checking Neo4j container '${CONTAINER}' is running..."
if ! docker inspect --format '{{.State.Running}}' "${CONTAINER}" 2>/dev/null | grep -q true; then
  echo "❌ Container '${CONTAINER}' is not running. Start it first with: docker compose up -d neo4j"
  exit 1
fi

echo "📊 Computing aggregate stats on Label nodes..."
echo "   This processes ~2.3M labels in batches of 100."
echo "   Most labels have <100 releases and compute quickly."
echo "   Large labels (e.g. Reprise Records with 55K releases) may take longer."
echo ""

docker exec "${CONTAINER}" cypher-shell \
  -u "${USER}" \
  -p "${PASSWORD}" \
  -d neo4j \
  "CALL {
        MATCH (l:Label)
        CALL {
            WITH l
            MATCH (l)<-[:ON]-(r:Release)
            RETURN count(DISTINCT r) AS rc
        }
        CALL {
            WITH l
            MATCH (l)<-[:ON]-(r:Release)-[:BY]->(a:Artist)
            RETURN count(DISTINCT a) AS ac
        }
        CALL {
            WITH l
            MATCH (l)<-[:ON]-(r:Release)-[:IS]->(g:Genre)
            RETURN count(DISTINCT g) AS gc
        }
        SET l.release_count = rc, l.artist_count = ac,
            l.genre_count = gc
    } IN TRANSACTIONS OF 100 ROWS"

echo ""
echo "✅ Label stats computed successfully."
echo ""
echo "🔍 Verifying — sample labels with stats:"
docker exec "${CONTAINER}" cypher-shell \
  -u "${USER}" \
  -p "${PASSWORD}" \
  -d neo4j \
  "MATCH (l:Label)
     WHERE l.release_count IS NOT NULL
     RETURN l.name AS label, l.release_count AS releases,
            l.artist_count AS artists, l.genre_count AS genres
     ORDER BY l.release_count DESC
     LIMIT 5"
