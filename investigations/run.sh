#!/usr/bin/env bash
# investigations/run.sh — One command to benchmark all graph databases.
#
# Local mode (default):
#   ./investigations/run.sh                       # Benchmark all databases locally at small scale
#   ./investigations/run.sh neo4j                 # Benchmark Neo4j only
#   ./investigations/run.sh neo4j large           # Benchmark Neo4j at large scale
#   ./investigations/run.sh --compare             # Compare all existing results
#
# Cloud mode:
#   ./investigations/run.sh --cloud               # Full Hetzner Cloud pipeline
#
# Prerequisites (local):
#   - Docker Desktop running
#   - uv installed (https://github.com/astral-sh/uv)
#   - Run from the repository root: ./investigations/run.sh
#
# Prerequisites (cloud):
#   - Hetzner Cloud API token (script will prompt if missing)
#   - Everything else is auto-installed
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

# ═══════════════════════════════════════════════════════
# Help
# ═══════════════════════════════════════════════════════

show_help() {
	echo "Usage: ./investigations/run.sh [OPTIONS] [backend] [scale]"
	echo ""
	echo "Modes:"
	echo "  (default)    Run benchmarks locally via Docker Compose"
	echo "  --cloud      Provision Hetzner Cloud infrastructure and benchmark there"
	echo ""
	echo "Local options:"
	echo "  backend      neo4j, memgraph, age, falkordb, arangodb (default: all)"
	echo "  scale        small, large (default: small)"
	echo "  --compare    Compare all existing result files"
	echo ""
	echo "Environment variables (optional, local mode):"
	echo "  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD"
	echo "  MEMGRAPH_URI"
	echo "  AGE_URI"
	echo "  FALKORDB_URI"
	echo "  ARANGODB_URI, ARANGODB_USER, ARANGODB_PASSWORD"
	echo "  BENCHMARK_SCALE (small or large)"
}

# ═══════════════════════════════════════════════════════
# Local mode
# ═══════════════════════════════════════════════════════

run_local() {
	cd "$REPO_ROOT"

	local SCALE="${BENCHMARK_SCALE:-small}"
	local TIMESTAMP
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

		local -a user_args=()
		if [[ -n "${DB_USER[$db]}" ]]; then
			user_args=("--user" "${DB_USER[$db]}" "--password" "${DB_PASSWORD[$db]}")
		fi

		uv run python -m investigations.benchmark.runner \
			--backend "$db" \
			--uri "${DB_URI[$db]}" \
			--scale "$scale" \
			--clear \
			--output "$output" \
			"${user_args[@]+"${user_args[@]}"}"

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

		if [[ ${#results[@]} -ge 2 ]]; then
			echo "Generating comparison..."
			uv run python -m investigations.benchmark.compare "${results[@]}"
		fi
	}

	# Install investigation dependencies
	echo "Installing dependencies..."
	uv sync --all-extras 2>/dev/null || true
	uv add --optional investigations neo4j 'psycopg[binary]' falkordb python-arango 2>/dev/null || true

	if [[ -n "${1:-}" ]]; then
		benchmark_single "$1" "${2:-$SCALE}"
	else
		benchmark_all "$SCALE"
	fi
}

compare_results() {
	cd "$REPO_ROOT"
	local files=(investigations/benchmark/results/*.json)
	if [[ ${#files[@]} -lt 2 ]]; then
		echo "Need at least 2 result files to compare."
		echo "Run benchmarks first: ./investigations/run.sh"
		exit 1
	fi
	uv run python -m investigations.benchmark.compare "${files[@]}"
}

# ═══════════════════════════════════════════════════════
# Cloud mode
# ═══════════════════════════════════════════════════════

run_cloud() {
	local INFRA_DIR="$SCRIPT_DIR/infra"
	local VAULT_FILE="$INFRA_DIR/vault.yml"
	local VAULT_PASS_FILE="$INFRA_DIR/.vault-pass"
	local SSH_KEY="$HOME/.ssh/benchmark-key"

	# --- Prerequisites ---
	echo "========================================"
	echo "  Checking prerequisites..."
	echo "========================================"

	# 1. uv
	if ! command -v uv &>/dev/null; then
		echo "Installing uv..."
		curl -LsSf https://astral.sh/uv/install.sh | sh
		export PATH="$HOME/.local/bin:$PATH"
	fi
	echo "  uv: $(command -v uv)"

	# 2. Ansible
	if ! command -v ansible-playbook &>/dev/null; then
		echo "Installing ansible-core via uv..."
		uv tool install ansible-core
	fi
	echo "  ansible: $(command -v ansible-playbook)"

	# 3. Ansible collections
	local REQUIRED_COLLECTIONS=("hetzner.hcloud" "community.docker" "community.general" "ansible.posix")
	for col in "${REQUIRED_COLLECTIONS[@]}"; do
		if ! ansible-galaxy collection list 2>/dev/null | grep -q "$col"; then
			echo "  Installing Ansible collection: $col"
			ansible-galaxy collection install "$col" --force-with-deps 2>/dev/null
		fi
	done
	echo "  Ansible collections: OK"

	# 4. hcloud Python package (required by hetzner.hcloud collection)
	if ! python3 -c "import hcloud" 2>/dev/null; then
		echo "  Installing hcloud Python package..."
		pip install --quiet hcloud 2>/dev/null || uv pip install hcloud 2>/dev/null || true
	fi

	# 5. SSH key
	if [[ ! -f "$SSH_KEY" ]]; then
		echo "  Generating SSH key at $SSH_KEY..."
		ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "discogsography-benchmark"
	fi
	echo "  SSH key: $SSH_KEY"

	# 6. Vault password file
	if [[ ! -f "$VAULT_PASS_FILE" ]]; then
		echo ""
		echo "  No vault password file found at $VAULT_PASS_FILE"
		read -rsp "  Enter a password to encrypt the Ansible vault (will be saved): " VAULT_PW
		echo ""
		echo "$VAULT_PW" >"$VAULT_PASS_FILE"
		chmod 600 "$VAULT_PASS_FILE"
		echo "  Vault password saved to $VAULT_PASS_FILE"
	fi

	local VAULT_ARGS="--vault-password-file=$VAULT_PASS_FILE"

	# 7. Vault file with Hetzner token
	if [[ ! -f "$VAULT_FILE" ]]; then
		echo ""
		echo "  No Ansible vault found. Creating one."
		echo "  You need a Hetzner Cloud API token."
		echo "  Get one at: https://console.hetzner.cloud > Project > Security > API Tokens"
		echo ""
		read -rsp "  Enter your Hetzner Cloud API token: " HCLOUD_TOKEN
		echo ""

		if [[ -z "$HCLOUD_TOKEN" ]]; then
			echo "ERROR: Token cannot be empty."
			exit 1
		fi

		echo "vault_hcloud_token: \"$HCLOUD_TOKEN\"" >"$VAULT_FILE.tmp"
		ansible-vault encrypt "$VAULT_FILE.tmp" "$VAULT_ARGS"
		mv "$VAULT_FILE.tmp" "$VAULT_FILE"
		echo "  Vault created at $VAULT_FILE"
	fi
	echo "  Vault: $VAULT_FILE"

	echo ""
	echo "  All prerequisites satisfied."
	echo ""

	# --- Deployment pipeline ---
	cd "$INFRA_DIR"

	echo "========================================"
	echo "  Discogsography Benchmark Pipeline"
	echo "========================================"
	echo ""
	echo "  Infrastructure: Hetzner Cloud (1x CX33 + 5x CX53)"
	echo "  Databases: Neo4j, Memgraph, AGE, FalkorDB, ArangoDB"
	echo "  Scale: small (~135k nodes) + large (~1.35M nodes)"
	echo "  Estimated cost: ~EUR 3.57 (24 hours)"
	echo ""
	read -rp "  Proceed? [Y/n] " proceed
	if [[ "${proceed:-Y}" =~ ^[Nn] ]]; then
		echo "Aborted."
		exit 0
	fi

	echo ""
	echo "=== Step 1/6: Provisioning Hetzner Cloud infrastructure ==="
	ansible-playbook playbooks/provision.yml "$VAULT_ARGS"

	echo ""
	echo "=== Step 2/6: Setting up all hosts (Docker, monitoring) ==="
	ansible-playbook playbooks/setup-common.yml

	echo ""
	echo "=== Step 3/6: Deploying databases ==="
	ansible-playbook playbooks/setup-neo4j.yml &
	local PID_NEO4J=$!
	ansible-playbook playbooks/setup-memgraph.yml &
	local PID_MEM=$!
	ansible-playbook playbooks/setup-age.yml &
	local PID_AGE=$!
	ansible-playbook playbooks/setup-falkordb.yml &
	local PID_FALK=$!
	ansible-playbook playbooks/setup-arangodb.yml &
	local PID_ARANGO=$!
	wait $PID_NEO4J $PID_MEM $PID_AGE $PID_FALK $PID_ARANGO
	echo "All databases deployed."

	echo ""
	echo "=== Step 4/6: Running benchmarks ==="
	ansible-playbook playbooks/run-benchmarks.yml

	echo ""
	echo "=== Step 5/6: Collecting results ==="
	ansible-playbook playbooks/collect-results.yml

	echo ""
	echo "========================================"
	echo "  Benchmarks complete!"
	echo "  Results saved to: investigations/benchmark/results/"
	echo "========================================"
	echo ""

	echo "=== Step 6/6: Teardown ==="
	echo ""
	echo "Options:"
	echo "  [d] Tear down database hosts only (keep controller for download)"
	echo "  [a] Tear down ALL infrastructure"
	echo "  [n] Keep everything running"
	echo ""
	read -rp "Choose [d/a/n]: " choice

	case "$choice" in
	d)
		echo "Tearing down database hosts (keeping controller)..."
		ansible-playbook playbooks/teardown.yml "$VAULT_ARGS" -e keep_controller=true
		echo "Controller still running. Full teardown later:"
		echo "  cd investigations/infra && ansible-playbook playbooks/teardown.yml $VAULT_ARGS"
		;;
	a)
		echo "Tearing down ALL infrastructure..."
		ansible-playbook playbooks/teardown.yml "$VAULT_ARGS"
		echo "Full teardown complete."
		;;
	*)
		echo "Infrastructure still running. Remember to tear down when done:"
		echo "  cd investigations/infra && ansible-playbook playbooks/teardown.yml $VAULT_ARGS"
		;;
	esac
}

# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

case "${1:-}" in
--help | -h)
	show_help
	exit 0
	;;
--compare)
	compare_results
	exit 0
	;;
--cloud)
	run_cloud
	exit 0
	;;
*)
	run_local "$@"
	;;
esac
