#!/usr/bin/env bash
# migrate-master-year-to-int.sh
#
# One-time migration: converts Master.year from string to integer in Neo4j.
#
# Background: prior to this fix, graphinator stored Master.year as a raw
# string value from the Discogs XML (e.g. "1969"). New ingests will write
# integers directly. Run this script once against an existing database to
# bring historical data in line without requiring a full re-ingest.
#
# Usage:
#   ./scripts/migrate-master-year-to-int.sh
#   NEO4J_CONTAINER=my-neo4j NEO4J_PASSWORD=secret ./scripts/migrate-master-year-to-int.sh
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

echo "📊 Counting Master nodes with non-null year before migration..."
BEFORE=$(docker exec "${CONTAINER}" cypher-shell \
    -u "${USER}" -p "${PASSWORD}" --format plain \
    "MATCH (m:Master) WHERE m.year IS NOT NULL RETURN count(m) AS n;" \
    | tail -1)
echo "   Found ${BEFORE} Master nodes with a year property."

echo ""
echo "🔄 Converting Master.year from string to integer..."
echo "   (Sets year=null where the value is absent, empty, or zero)"
echo ""

docker exec "${CONTAINER}" cypher-shell \
    -u "${USER}" -p "${PASSWORD}" \
    "MATCH (m:Master)
     WHERE m.year IS NOT NULL
     CALL {
       WITH m
       WITH m, toInteger(m.year) AS int_year
       SET m.year = CASE WHEN int_year > 0 THEN int_year ELSE null END
     } IN TRANSACTIONS OF 50000 ROWS;"

echo ""
echo "📊 Verifying results..."
INT_COUNT=$(docker exec "${CONTAINER}" cypher-shell \
    -u "${USER}" -p "${PASSWORD}" --format plain \
    "MATCH (m:Master) WHERE valueType(m.year) = 'LONG NOT NULL' RETURN count(m) AS n;" \
    | tail -1)
NULL_COUNT=$(docker exec "${CONTAINER}" cypher-shell \
    -u "${USER}" -p "${PASSWORD}" --format plain \
    "MATCH (m:Master) WHERE m.year IS NULL RETURN count(m) AS n;" \
    | tail -1)

echo "   ✅ ${INT_COUNT} Master nodes now have an integer year."
echo "   ℹ️  ${NULL_COUNT} Master nodes have no year (was 0, empty, or absent)."
echo ""
echo "✅ Migration complete."
