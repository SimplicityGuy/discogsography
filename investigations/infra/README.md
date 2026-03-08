# Hetzner Cloud Benchmark Infrastructure

Ansible automation for deploying 5 graph databases on Hetzner Cloud (Debian 13) and running benchmarks under identical conditions.

## One Command

```bash
./investigations/run.sh --cloud
```

This provisions 6 Hetzner Cloud servers, deploys all databases, runs benchmarks at both scale points, collects results, and optionally tears everything down. All prerequisites (Ansible, SSH keys, vault) are auto-installed — the only thing you need is a Hetzner Cloud API token.

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

# Hetzner CLI (for manual inspection if needed)
pip install hcloud

# SSH key for benchmark hosts
ssh-keygen -t ed25519 -f ~/.ssh/benchmark-key -N "" -C "discogsography-benchmark"
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| Vault password | Yes | Prompted by `--ask-vault-pass`, or use `--vault-password-file` |
| `HCLOUD_TOKEN` | No | Alternative to vault for Hetzner API token |

## Infrastructure

| Host | Instance | vCPU | RAM | Disk | Private IP | Role |
|------|----------|------|-----|------|------------|------|
| bench-controller | CX33 | 4 | 8 GB | 80 GB | 10.0.1.1 | Bastion, data gen, benchmark runner |
| bench-neo4j | CX53 | 16 | 32 GB | 320 GB | 10.0.1.10 | Neo4j Community |
| bench-memgraph | CX53 | 16 | 32 GB | 320 GB | 10.0.1.11 | Memgraph Community |
| bench-age | CX53 | 16 | 32 GB | 320 GB | 10.0.1.12 | PostgreSQL + Apache AGE |
| bench-falkordb | CX53 | 16 | 32 GB | 320 GB | 10.0.1.13 | FalkorDB |
| bench-arangodb | CX53 | 16 | 32 GB | 320 GB | 10.0.1.14 | ArangoDB Community |

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
```

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
