#!/usr/bin/env bash
# End-to-end: check prerequisites -> provision Hetzner Cloud -> deploy -> benchmark -> collect -> teardown.
#
# Usage:
#   ./investigations/infra/scripts/run-all.sh
#
# All prerequisites (SSH key, Ansible, collections, vault) are created
# automatically if they don't exist yet. The only thing you need is a
# Hetzner Cloud API token — the script will prompt for it if missing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VAULT_FILE="$INFRA_DIR/vault.yml"
VAULT_PASS_FILE="$INFRA_DIR/.vault-pass"
SSH_KEY="$HOME/.ssh/benchmark-key"

# ───────────────────────────────────────────────────────
# Prerequisites — auto-create if missing
# ───────────────────────────────────────────────────────

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
REQUIRED_COLLECTIONS=("hetzner.hcloud" "community.docker" "community.general" "ansible.posix")
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
    echo "$VAULT_PW" > "$VAULT_PASS_FILE"
    chmod 600 "$VAULT_PASS_FILE"
    echo "  Vault password saved to $VAULT_PASS_FILE"
fi

VAULT_ARGS="--vault-password-file=$VAULT_PASS_FILE"

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

    # Create vault file with the token
    echo "vault_hcloud_token: \"$HCLOUD_TOKEN\"" > "$VAULT_FILE.tmp"
    ansible-vault encrypt "$VAULT_FILE.tmp" "$VAULT_ARGS"
    mv "$VAULT_FILE.tmp" "$VAULT_FILE"
    echo "  Vault created at $VAULT_FILE"
fi
echo "  Vault: $VAULT_FILE"

echo ""
echo "  All prerequisites satisfied."
echo ""

# ───────────────────────────────────────────────────────
# Deployment pipeline
# ───────────────────────────────────────────────────────

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

# Step 1: Provision
echo ""
echo "=== Step 1/6: Provisioning Hetzner Cloud infrastructure ==="
ansible-playbook playbooks/provision.yml "$VAULT_ARGS"

# Step 2: Common setup
echo ""
echo "=== Step 2/6: Setting up all hosts (Docker, monitoring) ==="
ansible-playbook playbooks/setup-common.yml

# Step 3: Database setup (parallel)
echo ""
echo "=== Step 3/6: Deploying databases ==="
ansible-playbook playbooks/setup-neo4j.yml &
PID_NEO4J=$!
ansible-playbook playbooks/setup-memgraph.yml &
PID_MEM=$!
ansible-playbook playbooks/setup-age.yml &
PID_AGE=$!
ansible-playbook playbooks/setup-falkordb.yml &
PID_FALK=$!
ansible-playbook playbooks/setup-arangodb.yml &
PID_ARANGO=$!
wait $PID_NEO4J $PID_MEM $PID_AGE $PID_FALK $PID_ARANGO
echo "All databases deployed."

# Step 4: Run benchmarks
echo ""
echo "=== Step 4/6: Running benchmarks ==="
ansible-playbook playbooks/run-benchmarks.yml

# Step 5: Collect results
echo ""
echo "=== Step 5/6: Collecting results ==="
ansible-playbook playbooks/collect-results.yml

echo ""
echo "========================================"
echo "  Benchmarks complete!"
echo "  Results saved to: investigations/benchmark/results/"
echo "========================================"
echo ""

# Step 6: Teardown (with confirmation)
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
