#!/usr/bin/env bash
# investigations/run.sh — One command to benchmark all graph databases.
#
# Local mode (default):
#   ./investigations/run.sh                       # Benchmark all databases locally at small scale
#   ./investigations/run.sh neo4j                 # Benchmark Neo4j only
#   ./investigations/run.sh neo4j large           # Benchmark Neo4j at large scale
#   ./investigations/run.sh --compare             # Compare all existing result files
#
# Cloud mode (convergence — run repeatedly until all benchmarks complete):
#   ./investigations/run.sh --cloud               # First run: provisions controller + 3 DBs
#                                                 # Subsequent: tears down done, starts new
#   ./investigations/run.sh --cloud --server-limit 4   # Custom server limit (default: 5)
#
# Teardown:
#   ./investigations/run.sh --teardown            # Destroy all cloud infrastructure
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
	echo "  --cloud      Hetzner Cloud benchmark pipeline (convergence mode)"
	echo "  --fetch      Fetch results from cloud controller to investigations/results/"
	echo "  --teardown   Destroy all cloud infrastructure (alias: --terminate)"
	echo ""
	echo "Local options:"
	echo "  backend      neo4j, memgraph, age, falkordb, arangodb (default: all)"
	echo "  scale        small, large (default: small)"
	echo "  --compare    Compare all existing result files"
	echo ""
	echo "Cloud options:"
	echo "  --server-limit N   Max concurrent servers (default: 5)"
	echo "                     Run --cloud repeatedly to converge:"
	echo "                     1st run: provisions controller + 3 DB servers"
	echo "                     Next runs: tears down completed, starts remaining"
	echo "                     Final run: all done, only controller remains"
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

	# --- Configuration (bash 3.2 compatible — no associative arrays) ---
	db_compose() {
		case "$1" in
		neo4j) echo "investigations/docker/docker-compose.neo4j.yml" ;;
		memgraph) echo "investigations/docker/docker-compose.memgraph.yml" ;;
		age) echo "investigations/docker/docker-compose.age.yml" ;;
		falkordb) echo "investigations/docker/docker-compose.falkordb.yml" ;;
		arangodb) echo "investigations/docker/docker-compose.arangodb.yml" ;;
		esac
	}

	db_uri() {
		case "$1" in
		neo4j) echo "${NEO4J_URI:-bolt://localhost:7687}" ;;
		memgraph) echo "${MEMGRAPH_URI:-bolt://localhost:7688}" ;;
		age) echo "${AGE_URI:-postgresql://discogsography:discogsography@localhost:5433/discogsography}" ;;
		falkordb) echo "${FALKORDB_URI:-redis://localhost:6380}" ;;
		arangodb) echo "${ARANGODB_URI:-http://localhost:8529}" ;;
		esac
	}

	db_user() {
		case "$1" in
		neo4j) echo "${NEO4J_USER:-neo4j}" ;;
		arangodb) echo "${ARANGODB_USER:-root}" ;;
		*) echo "" ;;
		esac
	}

	db_password() {
		case "$1" in
		neo4j) echo "${NEO4J_PASSWORD:-discogsography}" ;;
		arangodb) echo "${ARANGODB_PASSWORD:-discogsography}" ;;
		*) echo "" ;;
		esac
	}

	start_db() {
		local db="$1"
		echo "Starting $db..."
		docker compose -f "$(db_compose "$db")" up -d --wait
		echo "$db is ready."
	}

	stop_db() {
		local db="$1"
		echo "Stopping $db..."
		docker compose -f "$(db_compose "$db")" down -v
	}

	run_benchmark() {
		local db="$1"
		local scale="${2:-$SCALE}"
		local output="investigations/results/${db}-${scale}-${TIMESTAMP}.json"

		echo ""
		echo "========================================"
		echo "  Benchmarking: $db (scale=$scale)"
		echo "========================================"

		local user pass
		user="$(db_user "$db")"
		pass="$(db_password "$db")"
		local -a user_args=()
		if [[ -n "$user" ]]; then
			user_args=("--user" "$user" "--password" "$pass")
		fi

		uv run python -m investigations.benchmark.runner \
			--backend "$db" \
			--uri "$(db_uri "$db")" \
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
			results+=("investigations/results/${db}-${scale}-${TIMESTAMP}.json")
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
	local files=(investigations/results/*.json)
	if [[ ${#files[@]} -lt 2 ]]; then
		echo "Need at least 2 result files to compare."
		echo "Run benchmarks first: ./investigations/run.sh"
		exit 1
	fi
	uv run python -m investigations.benchmark.compare "${files[@]}"
}

# ═══════════════════════════════════════════════════════
# Cloud mode — convergence-based
# ═══════════════════════════════════════════════════════
#
# Each invocation checks the current state of Hetzner infrastructure and
# benchmark results, then takes the next appropriate actions:
#
#   1st run:  No infrastructure → provision controller + 3 DB servers +
#             baseline calibration server. Run baseline calibration, copy
#             to controller, tear down baseline. Start benchmarks.
#   2nd+ run: Check results on controller. Tear down servers whose
#             benchmarks completed. Provision new servers for remaining
#             databases (up to server limit). Restart any failed benchmarks.
#   Final:    All 5 benchmarks done → tear down all DB servers, fetch
#             results. Only controller remains for manual inspection.
#

# Check if a value exists in a list of arguments
in_array() {
	local needle="$1"
	shift
	for v in "$@"; do
		[[ "$v" == "$needle" ]] && return 0
	done
	return 1
}

# Build a JSON array of strings from bash arguments: to_json_array a b c → ["a","b","c"]
to_json_array() {
	local result=""
	for v in "$@"; do
		result+="\"$v\","
	done
	echo "[${result%,}]"
}

cloud_prerequisites() {
	local INFRA_DIR="$1"
	local VAULT_FILE="$INFRA_DIR/vault.yml"
	local VAULT_PASS_FILE="$INFRA_DIR/.vault-pass"
	local SSH_KEY="$HOME/.ssh/benchmark-key"

	echo "========================================"
	echo "  Checking prerequisites..."
	echo "========================================"

	# uv
	if ! command -v uv &>/dev/null; then
		echo "Installing uv..."
		curl -LsSf https://astral.sh/uv/install.sh | sh
		export PATH="$HOME/.local/bin:$PATH"
	fi
	echo "  uv: $(command -v uv)"

	# Ansible
	if ! command -v ansible-playbook &>/dev/null; then
		echo "Installing ansible-core via uv..."
		uv tool install ansible-core
	fi
	echo "  ansible: $(command -v ansible-playbook)"

	# Ansible collections
	local REQUIRED_COLLECTIONS=("hetzner.hcloud" "community.docker" "community.general" "ansible.posix")
	for col in "${REQUIRED_COLLECTIONS[@]}"; do
		if ! ansible-galaxy collection list 2>/dev/null | grep -q "$col"; then
			echo "  Installing Ansible collection: $col"
			ansible-galaxy collection install "$col" --force-with-deps 2>/dev/null
		fi
	done
	echo "  Ansible collections: OK"

	# Ansible roles
	if ! ansible-galaxy role list 2>/dev/null | grep -q "geerlingguy.docker"; then
		echo "  Installing Ansible role: geerlingguy.docker"
		ansible-galaxy role install geerlingguy.docker 2>/dev/null
	fi
	echo "  Ansible roles: OK"

	# hcloud Python package (needed by hetzner.hcloud Ansible collection)
	if ! python3 -c "import hcloud" 2>/dev/null; then
		echo "  Installing hcloud Python package..."
		uv pip install --system hcloud 2>/dev/null || pip install --quiet hcloud 2>/dev/null || true
	fi

	# SSH key
	if [[ ! -f "$SSH_KEY" ]]; then
		echo "  Generating SSH key at $SSH_KEY..."
		ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "discogsography-benchmark"
	fi
	echo "  SSH key: $SSH_KEY"

	# Vault password file
	if [[ ! -f "$VAULT_PASS_FILE" ]]; then
		echo ""
		echo "  No vault password file found at $VAULT_PASS_FILE"
		read -rsp "  Enter a password to encrypt the Ansible vault (will be saved): " VAULT_PW
		echo ""
		echo "$VAULT_PW" >"$VAULT_PASS_FILE"
		chmod 600 "$VAULT_PASS_FILE"
		echo "  Vault password saved to $VAULT_PASS_FILE"
	fi

	# Vault file with Hetzner token
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
		ansible-vault encrypt "$VAULT_FILE.tmp" --vault-password-file="$VAULT_PASS_FILE"
		mv "$VAULT_FILE.tmp" "$VAULT_FILE"
		echo "  Vault created at $VAULT_FILE"
	fi
	echo "  Vault: $VAULT_FILE"

	echo ""
	echo "  All prerequisites satisfied."
	echo ""
}

run_cloud() {
	local INFRA_DIR="$SCRIPT_DIR/infra"
	local VAULT_PASS_FILE="$INFRA_DIR/.vault-pass"
	local SERVER_LIMIT="${SERVER_LIMIT:-5}"
	local INITIAL_BATCH=3

	# All databases to benchmark (order determines provisioning priority)
	local ALL_DBS=(neo4j memgraph age falkordb arangodb)

	cloud_prerequisites "$INFRA_DIR"

	local VAULT_ARGS="--vault-password-file=$VAULT_PASS_FILE"
	cd "$INFRA_DIR"

	# ── Step 1: Check existing infrastructure ─────────────────────
	echo "Checking Hetzner Cloud infrastructure..."
	if ! ansible-playbook playbooks/check-servers.yml "$VAULT_ARGS" >/dev/null 2>&1; then
		echo "ERROR: Could not query Hetzner Cloud API."
		echo "Check your API token and network connection."
		exit 1
	fi

	local CONTROLLER_IP=""
	local -a EXISTING_DB_SERVERS=()

	if [[ -f /tmp/bench-servers.txt ]]; then
		while IFS=' ' read -r name ip _status; do
			[[ -z "$name" ]] && continue
			if [[ "$name" == "bench-controller" ]]; then
				CONTROLLER_IP="$ip"
			elif [[ "$name" == bench-baseline ]]; then
				: # Skip baseline server — not a database
			elif [[ "$name" == bench-* ]]; then
				EXISTING_DB_SERVERS+=("${name#bench-}")
			fi
		done </tmp/bench-servers.txt
	fi

	# ── Step 2: First run — provision controller + initial batch ──
	if [[ -z "$CONTROLLER_IP" ]]; then
		local initial_dbs=("${ALL_DBS[@]:0:$INITIAL_BATCH}")

		echo ""
		echo "========================================"
		echo "  No existing infrastructure found."
		echo "  Starting initial deployment."
		echo "========================================"
		echo ""
		echo "  Infrastructure: 1x CX33 controller + ${#initial_dbs[@]}x CX53 databases + 1x CX53 baseline"
		echo "  Databases: ${initial_dbs[*]}"
		echo "  Server limit: $SERVER_LIMIT"
		echo "  Scale: small (~135k nodes) + large (~1.35M nodes)"
		echo ""
		read -rp "  Proceed? [Y/n] " proceed
		[[ "${proceed:-Y}" =~ ^[Nn] ]] && {
			echo "Aborted."
			exit 0
		}

		local dbs_json
		dbs_json=$(to_json_array "${initial_dbs[@]}")

		echo ""
		echo "=== Step 1/5: Provisioning ==="
		ansible-playbook playbooks/provision.yml "$VAULT_ARGS" \
			-e "{\"active_dbs\":$dbs_json,\"provision_baseline\":true}"

		echo ""
		echo "=== Step 2/5: Setting up hosts ==="
		ansible-playbook playbooks/setup-common.yml

		echo ""
		echo "=== Step 3/5: Baseline hardware calibration ==="
		ansible-playbook playbooks/baseline-calibration.yml
		echo "  Tearing down baseline instance..."
		ansible-playbook playbooks/teardown.yml "$VAULT_ARGS" \
			-e '{"destroy_servers":["bench-baseline"]}'

		echo ""
		echo "=== Step 4/5: Deploying databases ==="
		local -a db_pids=()
		for db in "${initial_dbs[@]}"; do
			ansible-playbook "playbooks/setup-${db}.yml" &
			db_pids+=($!)
		done
		local db_setup_failed=0
		for pid in "${db_pids[@]}"; do
			wait "$pid" || db_setup_failed=1
		done
		if [[ $db_setup_failed -eq 1 ]]; then
			echo ""
			echo "WARNING: One or more database setups failed."
			echo "  Run './investigations/run.sh --cloud' again to retry."
			echo "  The convergence loop will re-run setup for any failed databases."
			return
		fi

		echo ""
		echo "=== Step 5/5: Starting benchmarks ==="
		for db in "${initial_dbs[@]}"; do
			ansible-playbook playbooks/start-benchmark.yml \
				-e "benchmark_db=$db"
		done

		echo ""
		echo "========================================"
		echo "  Initial deployment complete!"
		echo "========================================"
		echo "  Benchmarks running: ${initial_dbs[*]}"
		echo "  Remaining: ${ALL_DBS[*]:$INITIAL_BATCH}"
		echo ""
		echo "  Run this command again to check progress and scale up."
		echo "  Monitor logs:"

		# Re-read controller IP from the generated inventory
		CONTROLLER_IP=$(grep -A1 'bench-controller' inventory/hosts.yml 2>/dev/null | grep ansible_host | awk '{print $2}' || echo '<controller-ip>')
		for db in "${initial_dbs[@]}"; do
			echo "    ssh -i ~/.ssh/benchmark-key root@${CONTROLLER_IP} 'tail -f /opt/benchmark/${db}-benchmark.log'"
		done
		return
	fi

	# ── Step 3: Controller exists — check benchmark status ────────
	echo ""
	echo "  Controller: $CONTROLLER_IP"
	echo "  DB servers: ${EXISTING_DB_SERVERS[*]:-none}"
	echo ""

	local -a COMPLETED_DBS=()
	local -a RUNNING_DBS=()
	local SSH_CMD="ssh -i $HOME/.ssh/benchmark-key -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@$CONTROLLER_IP"

	# Clean up stale PID files (process died without cleanup)
	$SSH_CMD 'for f in /opt/benchmark/*-benchmark.pid; do
		[ -f "$f" ] || continue
		pid=$(cat "$f" 2>/dev/null)
		if ! kill -0 "$pid" 2>/dev/null; then rm -f "$f"; fi
	done' 2>/dev/null || true

	# Gather sentinel (.done / .err / .timeout) and PID files
	local -a ERRORED_DBS=()
	local -a TIMED_OUT_DBS=()
	local status_output
	status_output=$($SSH_CMD 'echo "=DONE="; ls /opt/benchmark/results/*.done 2>/dev/null || true; echo "=ERR="; ls /opt/benchmark/results/*.err 2>/dev/null || true; echo "=PID="; ls /opt/benchmark/*-benchmark.pid 2>/dev/null || true; echo "=TIMEOUT="; ls /opt/benchmark/results/*.timeout 2>/dev/null || true' 2>/dev/null) || {
		echo "  Cannot reach controller at $CONTROLLER_IP. Try again in a few minutes."
		return
	}

	local in_done=false in_err=false in_pid=false in_timeout=false
	while IFS= read -r line; do
		case "$line" in
		"=DONE=")
			in_done=true
			in_err=false
			in_pid=false
			in_timeout=false
			continue
			;;
		"=ERR=")
			in_done=false
			in_err=true
			in_pid=false
			in_timeout=false
			continue
			;;
		"=PID=")
			in_done=false
			in_err=false
			in_pid=true
			in_timeout=false
			continue
			;;
		"=TIMEOUT=")
			in_done=false
			in_err=false
			in_pid=false
			in_timeout=true
			continue
			;;
		esac
		if $in_done; then
			local db_name
			db_name=$(basename "$line" .done)
			in_array "$db_name" "${ALL_DBS[@]}" && COMPLETED_DBS+=("$db_name")
		elif $in_err; then
			local db_name
			db_name=$(basename "$line" .err)
			in_array "$db_name" "${ALL_DBS[@]}" && ERRORED_DBS+=("$db_name")
		elif $in_pid; then
			local db_name
			db_name=$(basename "$line" -benchmark.pid)
			in_array "$db_name" "${ALL_DBS[@]}" && RUNNING_DBS+=("$db_name")
		elif $in_timeout; then
			local db_name
			db_name=$(basename "$line" .timeout)
			in_array "$db_name" "${ALL_DBS[@]}" && TIMED_OUT_DBS+=("$db_name")
		fi
	done <<<"$status_output"

	echo "  Completed:  ${COMPLETED_DBS[*]:-none}"
	[[ ${#TIMED_OUT_DBS[@]} -gt 0 ]] && echo "  Timed out:  ${TIMED_OUT_DBS[*]}"
	[[ ${#ERRORED_DBS[@]} -gt 0 ]] && echo "  Errored:    ${ERRORED_DBS[*]}"
	echo "  Running:    ${RUNNING_DBS[*]:-none}"

	# ── Step 3.4: Check for timeouts ────────────────────────────
	# If at least one benchmark has completed and others are still running,
	# check whether any running benchmark exceeds 5x the shortest completed duration.
	if [[ ${#COMPLETED_DBS[@]} -gt 0 ]] && [[ ${#RUNNING_DBS[@]} -gt 0 ]]; then
		local timing_output
		local all_dbs_str="${ALL_DBS[*]}"
		timing_output=$($SSH_CMD "
			NOW=\$(date +%s)
			for db in $all_dbs_str; do
				start_file=\"/opt/benchmark/results/\${db}.start\"
				[ -f \"\$start_file\" ] || continue
				start_epoch=\$(date -d \"\$(cat \"\$start_file\")\" +%s 2>/dev/null || echo 0)
				done_file=\"/opt/benchmark/results/\${db}.done\"
				if [ -f \"\$done_file\" ]; then
					done_epoch=\$(date -d \"\$(cat \"\$done_file\")\" +%s 2>/dev/null || echo 0)
					echo \"DURATION \$db \$((done_epoch - start_epoch))\"
				elif [ -f \"/opt/benchmark/\${db}-benchmark.pid\" ]; then
					echo \"ELAPSED \$db \$((NOW - start_epoch))\"
				fi
			done
		" 2>/dev/null) || true

		# Find shortest completed duration
		local shortest_duration=0
		while IFS=' ' read -r type db duration; do
			[[ "$type" == "DURATION" ]] || continue
			if [[ $shortest_duration -eq 0 ]] || [[ $duration -lt $shortest_duration ]]; then
				shortest_duration=$duration
			fi
		done <<<"$timing_output"

		if [[ $shortest_duration -gt 0 ]]; then
			local timeout_threshold=$((shortest_duration * 5))
			local -a newly_timed_out=()
			while IFS=' ' read -r type db elapsed; do
				[[ "$type" == "ELAPSED" ]] || continue
				if [[ $elapsed -gt $timeout_threshold ]]; then
					echo ""
					echo "  TIMEOUT: $db running ${elapsed}s (threshold: ${timeout_threshold}s = 5x shortest ${shortest_duration}s)"
					echo "  Marking $db as timed out..."

					$SSH_CMD "
						date -u '+%Y-%m-%dT%H:%M:%SZ' > /opt/benchmark/results/${db}.timeout
						cp /opt/benchmark/${db}-benchmark.log /opt/benchmark/results/${db}-timeout.log 2>/dev/null || true
						pid_file=/opt/benchmark/${db}-benchmark.pid
						if [ -f \"\$pid_file\" ]; then
							pid=\$(cat \"\$pid_file\")
							kill \$pid 2>/dev/null || true
							rm -f \"\$pid_file\"
						fi
					" 2>/dev/null || true

					TIMED_OUT_DBS+=("$db")
					newly_timed_out+=("$db")
				fi
			done <<<"$timing_output"

			# Remove newly timed out from RUNNING_DBS
			if [[ ${#newly_timed_out[@]} -gt 0 ]]; then
				local -a updated_running=()
				for r in ${RUNNING_DBS[@]+"${RUNNING_DBS[@]}"}; do
					in_array "$r" "${newly_timed_out[@]}" || updated_running+=("$r")
				done
				RUNNING_DBS=(${updated_running[@]+"${updated_running[@]}"})
			fi
		fi
	fi

	# ── Step 3.5: Ensure baseline calibration exists ─────────────
	local has_baseline
	has_baseline=$($SSH_CMD 'test -f /opt/benchmark/results/baseline-calibration.json && echo yes || echo no' 2>/dev/null) || has_baseline="no"

	if [[ "$has_baseline" != "yes" ]]; then
		echo ""
		echo "  Baseline calibration missing on controller — running calibration..."

		# Build current active DBs list for inventory
		local current_active_json
		current_active_json=$(to_json_array ${EXISTING_DB_SERVERS[@]+"${EXISTING_DB_SERVERS[@]}"})

		ansible-playbook playbooks/provision.yml "$VAULT_ARGS" \
			-e "{\"active_dbs\":$current_active_json,\"provision_baseline\":true}"
		ansible-playbook playbooks/baseline-calibration.yml
		ansible-playbook playbooks/teardown.yml "$VAULT_ARGS" \
			-e '{"destroy_servers":["bench-baseline"]}'

		# Re-generate inventory without baseline
		ansible-playbook playbooks/provision.yml "$VAULT_ARGS" \
			-e "{\"active_dbs\":$current_active_json}" >/dev/null 2>&1 || true

		echo "  Baseline calibration complete."
	fi

	# ── Step 4: All benchmarks done? ──────────────────────────────
	# Completed + timed out count as finished — errored ones will be retried.
	local finished_count=$(( ${#COMPLETED_DBS[@]} + ${#TIMED_OUT_DBS[@]} ))
	if [[ $finished_count -eq ${#ALL_DBS[@]} ]]; then
		echo ""
		echo "========================================"
		echo "  All benchmarks complete!"
		echo "========================================"

		# Tear down remaining DB servers
		if [[ ${#EXISTING_DB_SERVERS[@]} -gt 0 ]]; then
			echo ""
			echo "  Tearing down DB servers..."
			for db in ${EXISTING_DB_SERVERS[@]+"${EXISTING_DB_SERVERS[@]}"}; do
				echo "    bench-$db"
				ansible-playbook playbooks/teardown.yml "$VAULT_ARGS" \
					-e "{\"destroy_servers\":[\"bench-$db\"]}" >/dev/null 2>&1
			done
		fi

		# Update inventory to controller-only for fetch
		ansible-playbook playbooks/provision.yml "$VAULT_ARGS" \
			-e '{"active_dbs":[]}' >/dev/null 2>&1 || true

		echo ""
		echo "  Fetching results..."
		ansible-playbook playbooks/fetch-results.yml 2>/dev/null || true

		echo ""
		echo "  Results downloaded to investigations/results/"
		echo "  Controller still running at $CONTROLLER_IP for inspection."
		echo "  To tear down everything: ./investigations/run.sh --teardown"
		return
	fi

	# ── Step 5: Tear down completed/timed-out DB servers ─────────
	local -a torn_down=()
	for db in ${COMPLETED_DBS[@]+"${COMPLETED_DBS[@]}"} ${TIMED_OUT_DBS[@]+"${TIMED_OUT_DBS[@]}"}; do
		if in_array "$db" ${EXISTING_DB_SERVERS[@]+"${EXISTING_DB_SERVERS[@]}"}; then
			echo ""
			echo "  Tearing down bench-$db (benchmark complete)..."
			ansible-playbook playbooks/teardown.yml "$VAULT_ARGS" \
				-e "{\"destroy_servers\":[\"bench-$db\"]}"
			torn_down+=("$db")
		fi
	done

	# Build list of servers still running
	local -a active_dbs=()
	for db in ${EXISTING_DB_SERVERS[@]+"${EXISTING_DB_SERVERS[@]}"}; do
		in_array "$db" ${torn_down[@]+"${torn_down[@]}"} || active_dbs+=("$db")
	done
	local server_count=$((1 + ${#active_dbs[@]})) # controller + active DBs

	# ── Step 6: Retry failed/errored benchmarks ──────────────────
	# A server exists, benchmark isn't running, isn't complete, and isn't timed out → re-setup and restart.
	for db in ${active_dbs[@]+"${active_dbs[@]}"}; do
		if ! in_array "$db" ${COMPLETED_DBS[@]+"${COMPLETED_DBS[@]}"} && ! in_array "$db" ${RUNNING_DBS[@]+"${RUNNING_DBS[@]}"} && ! in_array "$db" ${TIMED_OUT_DBS[@]+"${TIMED_OUT_DBS[@]}"}; then
			echo ""
			if in_array "$db" ${ERRORED_DBS[@]+"${ERRORED_DBS[@]}"}; then
				echo "  Retrying errored benchmark for $db..."
				$SSH_CMD "rm -f /opt/benchmark/results/${db}.err /opt/benchmark/results/${db}-error.log" 2>/dev/null || true
			else
				echo "  Restarting benchmark for $db (previous run crashed)..."
			fi

			# Re-run setup to ensure Docker is installed and database is running
			ansible-playbook playbooks/setup-common.yml --limit "bench-controller,bench-$db"
			ansible-playbook "playbooks/setup-${db}.yml"
			ansible-playbook playbooks/start-benchmark.yml \
				-e "benchmark_db=$db"
		fi
	done

	# ── Step 7: Provision new DB servers ──────────────────────────
	local -a new_dbs=()
	for db in "${ALL_DBS[@]}"; do
		[[ $server_count -ge $SERVER_LIMIT ]] && break
		in_array "$db" ${COMPLETED_DBS[@]+"${COMPLETED_DBS[@]}"} && continue
		in_array "$db" ${TIMED_OUT_DBS[@]+"${TIMED_OUT_DBS[@]}"} && continue
		in_array "$db" ${active_dbs[@]+"${active_dbs[@]}"} && continue
		new_dbs+=("$db")
		server_count=$((server_count + 1))
	done

	if [[ ${#new_dbs[@]} -gt 0 ]] || [[ ${#torn_down[@]} -gt 0 ]]; then
		# Combine active + new for inventory
		local all_active=(${active_dbs[@]+"${active_dbs[@]}"} ${new_dbs[@]+"${new_dbs[@]}"})

		if [[ ${#all_active[@]} -gt 0 ]]; then
			local dbs_json
			dbs_json=$(to_json_array "${all_active[@]}")

			echo ""
			echo "=== Updating infrastructure ==="
			ansible-playbook playbooks/provision.yml "$VAULT_ARGS" \
				-e "{\"active_dbs\":$dbs_json}"
		elif [[ ${#torn_down[@]} -gt 0 ]]; then
			# All active servers torn down, no new ones — update inventory
			ansible-playbook playbooks/provision.yml "$VAULT_ARGS" \
				-e '{"active_dbs":[]}' >/dev/null 2>&1 || true
		fi

		for db in ${new_dbs[@]+"${new_dbs[@]}"}; do
			echo ""
			echo "=== Setting up bench-$db ==="
			ansible-playbook playbooks/setup-common.yml --limit "bench-$db"
			ansible-playbook "playbooks/setup-${db}.yml"
			ansible-playbook playbooks/start-benchmark.yml \
				-e "benchmark_db=$db"
		done
	fi

	# ── Step 8: Status report ─────────────────────────────────────
	local -a queued=()
	for db in "${ALL_DBS[@]}"; do
		in_array "$db" ${COMPLETED_DBS[@]+"${COMPLETED_DBS[@]}"} && continue
		in_array "$db" ${TIMED_OUT_DBS[@]+"${TIMED_OUT_DBS[@]}"} && continue
		in_array "$db" ${active_dbs[@]+"${active_dbs[@]}"} && continue
		in_array "$db" ${new_dbs[@]+"${new_dbs[@]}"} && continue
		queued+=("$db")
	done

	echo ""
	echo "========================================"
	echo "  Status ($finished_count/${#ALL_DBS[@]} finished)"
	echo "========================================"
	[[ ${#COMPLETED_DBS[@]} -gt 0 ]] && echo "  Done:    ${COMPLETED_DBS[*]}"
	[[ ${#TIMED_OUT_DBS[@]} -gt 0 ]] && echo "  Timeout: ${TIMED_OUT_DBS[*]}"
	local all_running=(${active_dbs[@]+"${active_dbs[@]}"} ${new_dbs[@]+"${new_dbs[@]}"})
	[[ ${#all_running[@]} -gt 0 ]] && echo "  Active:  ${all_running[*]}"
	[[ ${#queued[@]} -gt 0 ]] && echo "  Queued:  ${queued[*]}"
	echo "  Servers: $server_count / $SERVER_LIMIT"
	[[ ${#torn_down[@]} -gt 0 ]] && echo "  Freed:   ${torn_down[*]}"
	[[ ${#new_dbs[@]} -gt 0 ]] && echo "  Started: ${new_dbs[*]}"
	echo ""
	if [[ ${#queued[@]} -gt 0 ]] || [[ ${#all_running[@]} -gt 0 ]]; then
		echo "  Run this command again to check progress and continue."
	fi
}

# ═══════════════════════════════════════════════════════
# Fetch results
# ═══════════════════════════════════════════════════════

run_fetch() {
	local INFRA_DIR="$SCRIPT_DIR/infra"
	local VAULT_PASS_FILE="$INFRA_DIR/.vault-pass"

	if [[ ! -f "$VAULT_PASS_FILE" ]]; then
		echo "No vault password file found at $VAULT_PASS_FILE"
		echo "Run --cloud first to set up infrastructure."
		exit 1
	fi

	cd "$INFRA_DIR"

	echo "Fetching results from cloud infrastructure..."
	echo "  Destination: investigations/results/"
	echo ""

	ansible-playbook playbooks/fetch-results.yml

	echo ""
	echo "Results saved to investigations/results/"
}

# ═══════════════════════════════════════════════════════
# Teardown
# ═══════════════════════════════════════════════════════

run_teardown() {
	local INFRA_DIR="$SCRIPT_DIR/infra"
	local VAULT_PASS_FILE="$INFRA_DIR/.vault-pass"

	if [[ ! -f "$VAULT_PASS_FILE" ]]; then
		echo "No vault password file found at $VAULT_PASS_FILE"
		echo "Nothing to tear down."
		exit 1
	fi

	cd "$INFRA_DIR"
	echo "This will destroy ALL benchmark infrastructure (servers, network, firewalls)."
	read -rp "Proceed? [y/N] " proceed
	if [[ ! "${proceed:-N}" =~ ^[Yy] ]]; then
		echo "Aborted."
		exit 0
	fi

	ansible-playbook playbooks/teardown.yml \
		--vault-password-file="$VAULT_PASS_FILE"

	echo ""
	echo "Teardown complete. All cloud resources destroyed."
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
	shift
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--server-limit)
			export SERVER_LIMIT="$2"
			shift 2
			;;
		*)
			echo "Unknown cloud option: $1"
			show_help
			exit 1
			;;
		esac
	done
	run_cloud
	exit 0
	;;
--fetch)
	run_fetch
	exit 0
	;;
--teardown | --terminate)
	run_teardown
	exit 0
	;;
*)
	run_local "$@"
	;;
esac
