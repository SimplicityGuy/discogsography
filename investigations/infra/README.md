# Hetzner Cloud Benchmark Infrastructure

Ansible automation for deploying 5 graph databases on Hetzner Cloud (Debian 13) and running benchmarks under identical conditions.

## One Command

```bash
./investigations/run.sh --cloud
```

This uses a **convergence model** — run the command repeatedly and it advances the pipeline each time:

1. **1st run:** Provisions controller + 3 database servers + baseline calibration server. Runs baseline calibration, deploys databases, starts benchmarks.
2. **2nd+ runs:** Checks benchmark status on controller. Tears down completed servers. Provisions remaining databases (up to server limit). Retries failed benchmarks.
3. **Final run:** All 5 benchmarks done — tears down all DB servers, fetches results. Only controller remains for inspection.

All prerequisites (Ansible, SSH keys, vault) are auto-installed — the only thing you need is a Hetzner Cloud API token.

## Prerequisites

The `--cloud` flag auto-installs everything. For manual setup:

### 1. Hetzner account

1. Create account at [console.hetzner.cloud](https://console.hetzner.cloud)
2. Create project "discogsography-benchmark"
3. **Security > API Tokens > Generate API Token** (Read & Write)
4. Copy the token — the script will prompt for it on first run

### 2. Local tools (auto-installed by run.sh --cloud)

```bash
# Ansible
uv tool install ansible-core
ansible-galaxy collection install hetzner.hcloud community.docker community.general ansible.posix
ansible-galaxy role install geerlingguy.docker

# Hetzner Cloud Python package (needed by hetzner.hcloud Ansible collection)
uv pip install --system hcloud

# SSH key for benchmark hosts
ssh-keygen -t ed25519 -f ~/.ssh/benchmark-key -N "" -C "discogsography-benchmark"
```

## Commands

```bash
# Full cloud pipeline (convergence — run repeatedly)
./investigations/run.sh --cloud

# Limit concurrent servers (default: 5)
./investigations/run.sh --cloud --server-limit 3

# Fetch results from cloud to investigations/results/
./investigations/run.sh --fetch

# Destroy all cloud infrastructure
./investigations/run.sh --teardown

# Remove vault, vault password, and SSH keys
./investigations/run.sh --clean
```

## Infrastructure

| Host | Instance | vCPU | RAM | Disk | Private IP | Role |
|------|----------|------|-----|------|------------|------|
| bench-controller | CX33 | 4 | 8 GB | 80 GB | 10.0.1.1 | Bastion, data gen, benchmark orchestration |
| bench-neo4j | CX53 | 16 | 32 GB | 320 GB | 10.0.1.10 | Neo4j Community |
| bench-memgraph | CX53 | 16 | 32 GB | 320 GB | 10.0.1.11 | Memgraph Community |
| bench-age | CX53 | 16 | 32 GB | 320 GB | 10.0.1.12 | PostgreSQL + Apache AGE |
| bench-falkordb | CX53 | 16 | 32 GB | 320 GB | 10.0.1.13 | FalkorDB |
| bench-arangodb | CX53 | 16 | 32 GB | 320 GB | 10.0.1.14 | ArangoDB Community |
| bench-baseline | CX53 | 16 | 32 GB | 320 GB | — | Hardware calibration (temporary) |

### Network Security

- **Controller**: SSH accessible from the internet (only port 22). Interactive `bench` user with sudo.
- **Database hosts**: Only reachable from the private network (10.0.1.0/24). No internet-facing ports.
- Ansible reaches database hosts via SSH ProxyJump through the controller.

### SSH Access

```bash
# SSH to controller as interactive user
ssh -i ~/.ssh/benchmark-key bench@<controller-ip>

# SSH to a database host (via controller bastion)
ssh -i ~/.ssh/benchmark-key -J root@<controller-ip> root@10.0.1.10

# Tail benchmark logs
ssh -i ~/.ssh/benchmark-key root@<controller-ip> 'tail -f /opt/benchmark/neo4j-benchmark.log'
```

### Cost

| Duration | Controller (1x CX33) | DB Hosts (5x CX53) | Total |
|----------|---------------------|---------------------|-------|
| 8 hours | €0.07 | €1.12 | **€1.19** |
| 24 hours | €0.21 | €3.36 | **€3.57** |
| 48 hours | €0.42 | €6.72 | **€7.14** |

Set a $75 billing alert in Hetzner Console > Account > Billing.

## Convergence Model

The `--cloud` flag implements a convergence loop with sentinel-file-based status tracking:

### Sentinel Files (on controller at `/opt/benchmark/results/`)

| File | Meaning |
|------|---------|
| `{db}.done` | Benchmark completed successfully (contains timestamp) |
| `{db}.err` | Benchmark errored (contains timestamp) |
| `{db}.timeout` | Benchmark timed out (contains timestamp) |
| `{db}.start` | Benchmark start time |

### PID Files (on controller at `/opt/benchmark/`)

| File | Meaning |
|------|---------|
| `{db}-benchmark.pid` | Benchmark is currently running |
| `{db}-benchmark.log` | Benchmark stdout/stderr |

### Timeout Detection

When at least one benchmark has completed and others are still running, the script checks whether any running benchmark exceeds **5x the shortest completed duration**. If so, it kills the benchmark process and marks it as timed out.

### Per-Database Runner

Each database gets its own shell script (`run-benchmark-{db}.sh`) deployed from the `run-benchmark-single.sh.j2` template. The runner:
1. Sets database-specific URIs and credentials
2. Runs benchmarks at both scale points (small + large)
3. Creates `.done` or `.err` sentinel files on completion

## Playbooks

| Playbook | Description |
|----------|-------------|
| `provision.yml` | Create Hetzner servers, network, firewalls. Supports wave mode via `active_dbs` variable. |
| `setup-common.yml` | Install Docker, monitoring tools, metrics collector, and `bench` user on all hosts |
| `setup-{neo4j,memgraph,age,falkordb,arangodb}.yml` | Deploy Docker Compose template and start each database |
| `start-benchmark.yml` | Sync code to controller, install dependencies, generate data, calibrate host, start benchmark in background |
| `baseline-calibration.yml` | Run hardware calibration on baseline server and copy results to controller |
| `check-servers.yml` | Query Hetzner API for current infrastructure state |
| `fetch-results.yml` | Check status and fetch results, logs, calibration, and metrics to local machine |
| `run-benchmarks.yml` | Legacy orchestration playbook (superseded by `run.sh --cloud` convergence loop) |
| `teardown.yml` | Destroy servers, network, firewalls. Supports selective teardown via `destroy_servers` variable. |

### Individual playbook usage

```bash
cd investigations/infra

# Provision controller + specific databases
ansible-playbook playbooks/provision.yml --vault-password-file=.vault-pass \
  -e '{"active_dbs": ["neo4j", "memgraph"]}'

# Setup one database
ansible-playbook playbooks/setup-neo4j.yml

# Start benchmark for a single database
ansible-playbook playbooks/start-benchmark.yml -e benchmark_db=neo4j

# Check status and fetch results (safe to run while benchmarks are in progress)
ansible-playbook playbooks/fetch-results.yml

# Selective teardown (remove specific servers)
ansible-playbook playbooks/teardown.yml --vault-password-file=.vault-pass \
  -e '{"destroy_servers": ["bench-neo4j", "bench-memgraph"]}'

# Full teardown
ansible-playbook playbooks/teardown.yml --vault-password-file=.vault-pass
```

## Templates

| Template | Description |
|----------|-------------|
| `docker-compose.{neo4j,memgraph,age,falkordb,arangodb}.yml.j2` | Per-database Docker Compose configs |
| `run-benchmark-single.sh.j2` | Per-database benchmark runner script |
| `run-benchmarks.sh.j2` | Legacy multi-database runner |
| `metrics-collector.sh.j2` | System metrics collection script (CPU, memory, I/O, network) |

## Controller File Layout

```
/opt/benchmark/
├── discogsography/investigations/   # Code synced from local repo
├── data/                            # Synthetic data files (cached)
│   ├── synthetic-data-small-{date}.json.gz
│   └── synthetic-data-large-{date}.json.gz
├── results/                         # All results + sentinel files
│   ├── {db}-small-{timestamp}.json  # Benchmark result
│   ├── {db}-large-{timestamp}.json  # Benchmark result
│   ├── {db}.done / .err / .timeout  # Status sentinels
│   ├── {db}.start                   # Start timestamp
│   ├── {db}-calibration.json        # Per-host hardware calibration
│   ├── baseline-calibration.json    # Baseline reference
│   └── {db}-system-metrics.jsonl    # System metrics
├── {db}-benchmark.pid               # Running process ID
├── {db}-benchmark.log               # stdout/stderr
├── run-benchmark-{db}.sh            # Per-DB runner script
└── metrics-collector.sh             # Metrics background script
```

## Files Not in Git

These are excluded via `.gitignore`:

```
investigations/infra/vault.yml
investigations/infra/.vault-pass
investigations/infra/inventory/hosts.yml
```
