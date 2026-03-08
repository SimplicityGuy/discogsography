# Hetzner Cloud Benchmark Infrastructure

Ansible automation for deploying 5 graph databases on Hetzner Cloud and running benchmarks under identical conditions.

## One Command

```bash
./investigations/infra/scripts/run-all.sh
```

This provisions 6 Hetzner Cloud servers, deploys all databases, runs benchmarks at both scale points, collects results, and optionally tears everything down.

## Prerequisites

### 1. Local tools

```bash
# Ansible
uv tool install ansible-core
ansible-galaxy collection install hetzner.hcloud community.docker community.general ansible.posix

# Hetzner CLI (for manual inspection if needed)
pip install hcloud

# SSH key for benchmark hosts
ssh-keygen -t ed25519 -f ~/.ssh/benchmark-key -N "" -C "discogsography-benchmark"
```

### 2. Hetzner account

1. Create account at [console.hetzner.cloud](https://console.hetzner.cloud)
2. Create project "discogsography-benchmark"
3. **Security > API Tokens > Generate API Token** (Read & Write)
4. Copy the token

### 3. Ansible vault

```bash
cd investigations/infra
ansible-vault create vault.yml
```

Contents:
```yaml
vault_hcloud_token: "your-hetzner-api-token-here"
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| Vault password | Yes | Prompted by `--ask-vault-pass`, or use `--vault-password-file` |
| `HCLOUD_TOKEN` | No | Alternative to vault for Hetzner API token |

## Infrastructure

| Host | Instance | vCPU | RAM | Disk | Role |
|------|----------|------|-----|------|------|
| bench-controller | CX33 | 4 | 8 GB | 80 GB | Ansible, data gen, benchmark runner |
| bench-neo4j | CX53 | 16 | 32 GB | 320 GB | Neo4j Community |
| bench-memgraph | CX53 | 16 | 32 GB | 320 GB | Memgraph Community |
| bench-age | CX53 | 16 | 32 GB | 320 GB | PostgreSQL + Apache AGE |
| bench-falkordb | CX53 | 16 | 32 GB | 320 GB | FalkorDB |
| bench-arangodb | CX53 | 16 | 32 GB | 320 GB | ArangoDB Community |

### Cost

| Duration | Controller (1x CX33) | DB Hosts (5x CX53) | Total |
|----------|---------------------|---------------------|-------|
| 8 hours | EUR 0.07 | EUR 1.12 | **EUR 1.19** |
| 24 hours | EUR 0.21 | EUR 3.36 | **EUR 3.57** |
| 48 hours | EUR 0.42 | EUR 6.72 | **EUR 7.14** |

Set a $75 billing alert in Hetzner Console > Account > Billing.

## Playbooks

| Playbook | Description |
|----------|-------------|
| `provision.yml` | Create Hetzner servers, network, firewall |
| `setup-common.yml` | Install Docker and monitoring on all hosts |
| `setup-{neo4j,memgraph,age,falkordb,arangodb}.yml` | Deploy each database |
| `run-benchmarks.yml` | Generate data, insert, run query benchmarks |
| `collect-results.yml` | Fetch results to local machine |
| `teardown.yml` | Destroy all infrastructure |

### Individual playbook usage

```bash
cd investigations/infra

# Provision only
ansible-playbook playbooks/provision.yml --ask-vault-pass

# Setup one database
ansible-playbook playbooks/setup-neo4j.yml

# Run benchmarks
ansible-playbook playbooks/run-benchmarks.yml

# Collect results
ansible-playbook playbooks/collect-results.yml

# Partial teardown (keep controller for download)
ansible-playbook playbooks/teardown.yml --ask-vault-pass -e keep_controller=true

# Full teardown
ansible-playbook playbooks/teardown.yml --ask-vault-pass
```

## Files Not in Git

Add to `.gitignore`:
```
investigations/infra/vault.yml
investigations/infra/.vault-pass
investigations/infra/inventory/hosts.yml
```
