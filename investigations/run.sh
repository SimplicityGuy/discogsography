#!/usr/bin/env bash
# investigations/run.sh — One command to benchmark all graph databases locally.
#
# Usage:
#   ./investigations/run.sh                     # Benchmark all databases at small scale
#   ./investigations/run.sh neo4j               # Benchmark Neo4j only
#   ./investigations/run.sh neo4j large          # Benchmark Neo4j at large scale
#   ./investigations/run.sh --compare           # Compare all existing results
#
# Prerequisites:
#   - Docker Desktop running
#   - uv installed (https://github.com/astral-sh/uv)
#   - Run from the repository root: ./investigations/run.sh
#
# Environment variables (all optional — defaults work for local Docker):
#   NEO4J_URI          bolt://localhost:7687
#   NEO4J_USER         neo4j
#   NEO4J_PASSWORD     discogsography
#   MEMGRAPH_URI       bolt://localhost:7688
#   AGE_URI            postgresql://discogsography:discogsography@localhost:5433/discogsography
#   FALKORDB_URI       redis://localhost:6380
#   ARANGODB_URI       http://localhost:8529
#   ARANGODB_USER      root
#   ARANGODB_PASSWORD  discogsography
#   BENCHMARK_SCALE    small (or large)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SCALE="${BENCHMARK_SCALE:-small}"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)

# --- Configuration ---
declare -A DB_COMPOSE DB_URI DB_USER DB_PASSWORD
DB_COMPOSE=(
    [neo4j]="investigations/docker/docker-compose.neo4j.yml"
    [memgraph]="investigations/docker/docker-compose.memgraph.yml"
    [age]="investigations/docker/docker-compose.age.yml"
    [falkordb]="investigations/docker/docker-compose.falkordb.yml"
    [arangodb]="investigations/docker/docker-compose.arangodb.yml"
)
DB_URI=(
    [neo4j]="${NEO4J_URI:-bolt://localhost:7687}"
    [memgraph]="${MEMGRAPH_URI:-bolt://localhost:7688}"
    [age]="${AGE_URI:-postgresql://discogsography:discogsography@localhost:5433/discogsography}"
    [falkordb]="${FALKORDB_URI:-redis://localhost:6380}"
    [arangodb]="${ARANGODB_URI:-http://localhost:8529}"
)
DB_USER=(
    [neo4j]="${NEO4J_USER:-neo4j}"
    [memgraph]=""
    [age]=""
    [falkordb]=""
    [arangodb]="${ARANGODB_USER:-root}"
)
DB_PASSWORD=(
    [neo4j]="${NEO4J_PASSWORD:-discogsography}"
    [memgraph]=""
    [age]=""
    [falkordb]=""
    [arangodb]="${ARANGODB_PASSWORD:-discogsography}"
)

# --- Functions ---

start_db() {
    local db="$1"
    echo "Starting $db..."
    docker compose -f "${DB_COMPOSE[$db]}" up -d --wait
    echo "$db is ready."
}

stop_db() {
    local db="$1"
    echo "Stopping $db..."
    docker compose -f "${DB_COMPOSE[$db]}" down -v
}

run_benchmark() {
    local db="$1"
    local scale="${2:-$SCALE}"
    local output="investigations/benchmark/results/${db}_${scale}_${TIMESTAMP}.json"

    echo ""
    echo "========================================"
    echo "  Benchmarking: $db (scale=$scale)"
    echo "========================================"

    local user_args=""
    if [[ -n "${DB_USER[$db]}" ]]; then
        user_args="--user ${DB_USER[$db]} --password ${DB_PASSWORD[$db]}"
    fi

    uv run python -m investigations.benchmark.runner \
        --backend "$db" \
        --uri "${DB_URI[$db]}" \
        --scale "$scale" \
        --clear \
        --output "$output" \
        $user_args

    echo "Results: $output"
}

benchmark_single() {
    local db="$1"
    local scale="${2:-$SCALE}"

    start_db "$db"
    run_benchmark "$db" "$scale"
    stop_db "$db"
}

benchmark_all() {
    local scale="${1:-$SCALE}"
    local results=()

    for db in neo4j memgraph falkordb arangodb age; do
        echo ""
        echo "########################################"
        echo "  Starting $db benchmark"
        echo "########################################"

        start_db "$db"
        run_benchmark "$db" "$scale"
        results+=("investigations/benchmark/results/${db}_${scale}_${TIMESTAMP}.json")
        stop_db "$db"
    done

    echo ""
    echo "========================================"
    echo "  All benchmarks complete!"
    echo "========================================"
    echo ""

    # Run comparison if we have results
    if [[ ${#results[@]} -ge 2 ]]; then
        echo "Generating comparison..."
        uv run python -m investigations.benchmark.compare "${results[@]}"
    fi
}

compare_results() {
    local files=(investigations/benchmark/results/*.json)
    if [[ ${#files[@]} -lt 2 ]]; then
        echo "Need at least 2 result files to compare."
        echo "Run benchmarks first: ./investigations/run.sh"
        exit 1
    fi
    uv run python -m investigations.benchmark.compare "${files[@]}"
}

# --- Main ---

if [[ "${1:-}" == "--compare" ]]; then
    compare_results
    exit 0
fi

if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    echo "Usage: ./investigations/run.sh [backend] [scale]"
    echo ""
    echo "  backend: neo4j, memgraph, age, falkordb, arangodb (default: all)"
    echo "  scale:   small, large (default: small)"
    echo ""
    echo "Options:"
    echo "  --compare    Compare all existing result files"
    echo "  --help       Show this help"
    echo ""
    echo "Environment variables (optional):"
    echo "  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD"
    echo "  MEMGRAPH_URI"
    echo "  AGE_URI"
    echo "  FALKORDB_URI"
    echo "  ARANGODB_URI, ARANGODB_USER, ARANGODB_PASSWORD"
    echo "  BENCHMARK_SCALE (small or large)"
    exit 0
fi

# Install investigation dependencies
echo "Installing dependencies..."
uv sync --all-extras 2>/dev/null || true
uv add --optional investigations neo4j 'psycopg[binary]' falkordb python-arango 2>/dev/null || true

if [[ -n "${1:-}" ]]; then
    benchmark_single "$1" "${2:-$SCALE}"
else
    benchmark_all "$SCALE"
fi
