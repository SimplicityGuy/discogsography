#!/usr/bin/env bash
# cleanup-implausible-years.sh
#
# One-time cleanup: nulls out implausible release/master years from existing
# data in Neo4j and PostgreSQL.
#
# Background: a Discogs *release* carries its date in <released> (a date string),
# not <year>, so the extractor's year-range rules — which key on the `year`
# field — never fired for releases. The release year is derived consumer-side
# in common/data_normalizer.py, which (prior to this fix) only rejected year 0.
# As a result, releases with antiquity/sentinel dates (e.g. "0400-01-01") were
# stored as year 400, polluting the Insights "Genre Trends" chart.
#
# The code fix (common/data_normalizer.py) stops new bad years at ingest. This
# script brings *existing* data in line without a full re-ingest. New ingests
# need no cleanup.
#
# Scope: Discogs Release/Master nodes (Neo4j) and the public `releases`/`masters`
# tables (PostgreSQL). MusicBrainz entities take a different ingest path and are
# out of scope.
#
# Plausible range: [1860, current_year + 1] — must stay in sync with
# MIN_RELEASE_YEAR in common/data_normalizer.py and extractor/extraction-rules.yaml.
#
# Usage:
#   ./scripts/cleanup-implausible-years.sh            # dry run — counts only, no changes
#   ./scripts/cleanup-implausible-years.sh --apply    # perform the cleanup
#
# Environment variables (all optional, defaults shown):
#   NEO4J_CONTAINER     docker container name  (default: discogsography-neo4j)
#   NEO4J_USER          Neo4j username         (default: neo4j)
#   NEO4J_PASSWORD      Neo4j password         (default: discogsography)
#   POSTGRES_CONTAINER  docker container name  (default: discogsography-postgres)
#   POSTGRES_USER       PostgreSQL username    (default: discogsography)
#   POSTGRES_DB         PostgreSQL database    (default: discogsography)

set -euo pipefail

NEO4J_CONTAINER="${NEO4J_CONTAINER:-discogsography-neo4j}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-discogsography}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-discogsography-postgres}"
POSTGRES_USER="${POSTGRES_USER:-discogsography}"
POSTGRES_DB="${POSTGRES_DB:-discogsography}"

MIN_YEAR=1860
MAX_YEAR=$(($(date +%Y) + 1))

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
elif [[ -n "${1:-}" ]]; then
  echo "❌ Unknown argument '${1}'. Use --apply to perform the cleanup (omit for a dry run)."
  exit 1
fi

if [[ "${APPLY}" -eq 1 ]]; then
  echo "⚠️  APPLY mode: implausible years will be set to null."
else
  echo "🧪 DRY RUN: counting affected records only. Re-run with --apply to make changes."
fi
echo "📅 Plausible year range: [${MIN_YEAR}, ${MAX_YEAR}]"
echo ""

run_neo4j() {
  docker exec "${NEO4J_CONTAINER}" cypher-shell -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" "$@"
}

run_pg() {
  docker exec "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A "$@"
}

# ── Neo4j ──────────────────────────────────────────────────────────────────
echo "🔍 Checking Neo4j container '${NEO4J_CONTAINER}' is running..."
if ! docker inspect --format '{{.State.Running}}' "${NEO4J_CONTAINER}" 2>/dev/null | grep -q true; then
  echo "❌ Container '${NEO4J_CONTAINER}' is not running. Start it first with: docker compose up -d neo4j"
  exit 1
fi

for label in Release Master; do
  COUNT=$(run_neo4j --format plain \
    "MATCH (n:${label}) WHERE n.year IS NOT NULL AND (n.year < ${MIN_YEAR} OR n.year > ${MAX_YEAR}) RETURN count(n) AS n;" |
    tail -1)
  echo "   ${label}: ${COUNT} node(s) with an implausible year."
  if [[ "${APPLY}" -eq 1 && "${COUNT}" -gt 0 ]]; then
    echo "   🔄 Nulling ${label}.year for out-of-range values..."
    run_neo4j \
      "MATCH (n:${label})
         WHERE n.year IS NOT NULL AND (n.year < ${MIN_YEAR} OR n.year > ${MAX_YEAR})
         CALL { WITH n SET n.year = null } IN TRANSACTIONS OF 50000 ROWS;"
  fi
done
echo ""

# ── PostgreSQL ───────────────────────────────────────────────────────────────
echo "🔍 Checking PostgreSQL container '${POSTGRES_CONTAINER}' is running..."
if ! docker inspect --format '{{.State.Running}}' "${POSTGRES_CONTAINER}" 2>/dev/null | grep -q true; then
  echo "❌ Container '${POSTGRES_CONTAINER}' is not running. Start it first with: docker compose up -d postgres"
  exit 1
fi

for table in releases masters; do
  COUNT=$(run_pg -c \
    "SELECT count(*) FROM ${table}
       WHERE data->>'year' ~ '^[0-9]+\$'
         AND ((data->>'year')::int < ${MIN_YEAR} OR (data->>'year')::int > ${MAX_YEAR});")
  echo "   ${table}: ${COUNT} row(s) with an implausible year."
  if [[ "${APPLY}" -eq 1 && "${COUNT}" -gt 0 ]]; then
    echo "   🔄 Setting ${table}.data->'year' to null for out-of-range values..."
    run_pg -c \
      "UPDATE ${table}
         SET data = jsonb_set(data, '{year}', 'null'::jsonb)
       WHERE data->>'year' ~ '^[0-9]+\$'
         AND ((data->>'year')::int < ${MIN_YEAR} OR (data->>'year')::int > ${MAX_YEAR});"
  fi
done
echo ""

if [[ "${APPLY}" -eq 1 ]]; then
  echo "✅ Cleanup complete."
else
  echo "✅ Dry run complete. Re-run with --apply to null the years counted above."
fi
