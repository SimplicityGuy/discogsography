# Cloud Benchmark Deployment Plan

## Overview

Deploy 6 dedicated hosts to benchmark Neo4j, Memgraph, Apache AGE, FalkorDB, and ArangoDB under identical conditions. A single extractor+RabbitMQ host fans out messages to database-specific queues, and each database host runs its own graphinator variant consuming from its dedicated queue.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Host 1: Extractor + RabbitMQ                   │
│                                                 │
│  ┌───────────┐     ┌──────────────────────────┐ │
│  │ Extractor  │────>│ RabbitMQ (5 exchanges)   │ │
│  │ (Rust)     │     │                          │ │
│  └───────────┘     │  neo4j-exchange ─────────┼──────> Host 2
│                     │  memgraph-exchange ──────┼──────> Host 3
│                     │  age-exchange ───────────┼──────> Host 4
│                     │  falkordb-exchange ──────┼──────> Host 5
│                     │  arangodb-exchange ──────┼──────> Host 6
│                     └──────────────────────────┘ │
└─────────────────────────────────────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Host 2: Neo4j    │  │ Host 3: Memgraph │  │ Host 4: AGE      │
│ + graphinator    │  │ + graphinator    │  │ + graphinator    │
│   [neo4j]        │  │   [memgraph]     │  │   [age]          │
└──────────────────┘  └──────────────────┘  └──────────────────┘

┌──────────────────┐  ┌──────────────────┐
│ Host 5: FalkorDB │  │ Host 6: ArangoDB │
│ + graphinator    │  │ + graphinator    │
│   [falkordb]     │  │   [arangodb]     │
└──────────────────┘  └──────────────────┘
```

## Design Decisions and Recommendations

### Is This a Good Approach?

Yes, with adjustments. Dedicated hosts per database eliminates resource contention — the primary confounder in benchmarks. Some refinements:

**Recommended adjustments:**

1. **Run benchmarks sequentially, not during import.** Import all 5 databases first, then run read benchmarks after. This prevents network/RabbitMQ contention from affecting import metrics.

2. **Use the same RabbitMQ instance but separate exchanges/queues per backend.** Avoids 5x RabbitMQ overhead. The extractor publishes each record once but to 5 routing keys — the fan-out overhead is minimal since messages are small JSON.

3. **Add a 7th "controller" role to Host 1.** After import completes, Host 1 runs the benchmark harness, issuing queries to each database host over the network. This simulates real API latency and avoids co-locating the benchmark runner with the database.

4. **Collect metrics via a lightweight agent (node_exporter + custom script)** rather than polling from a central host. Each host pushes metrics to Host 1 periodically.

5. **Run the full benchmark twice** — once to warm caches, once for final measurements. Discard the warmup run.

6. **Snapshot disk after import** (where supported) so benchmarks can be re-run without re-importing.

### Extractor Fan-Out Design

The current extractor publishes to a single exchange (`discogsography-exchange`) with topic routing. Graphinator and tableinator bind their own queues to this exchange.

For the benchmark, expand to **5 exchanges** (one per backend). The extractor publishes each message 5 times — once per exchange. This is simpler than a single exchange with complex routing, and ensures each backend gets its own independent queue with no message sharing.

```rust
// Simplified: publish to all benchmark exchanges
const BENCHMARK_EXCHANGES: &[&str] = &[
    "bench-neo4j",
    "bench-memgraph",
    "bench-age",
    "bench-falkordb",
    "bench-arangodb",
];

pub async fn publish_to_all(&self, message: Message, data_type: DataType) -> Result<()> {
    for exchange in BENCHMARK_EXCHANGES {
        self.channel
            .basic_publish(exchange, data_type.routing_key(), ...)
            .await?;
    }
    Ok(())
}
```

Each database host's graphinator binds to its own exchange (e.g., `bench-neo4j`) and consumes from `bench-neo4j-graphinator-{artists,labels,masters,releases}`.

**Alternative (lower overhead):** Use a single exchange with a fanout type. RabbitMQ copies each message to all bound queues. The extractor publishes once, RabbitMQ handles duplication. This is simpler to implement and uses less extractor CPU:

```rust
// Single fanout exchange — RabbitMQ duplicates to all bound queues
const BENCHMARK_EXCHANGE: &str = "bench-fanout";
// Exchange type: "fanout" (not "topic")
// Each graphinator binds its own queue to this exchange
```

**Recommendation:** Use the fanout exchange approach. It's simpler, publishes each message once, and RabbitMQ handles the fan-out natively.

## Cloud Provider Comparison

### Recommended: Hetzner Cloud

Hetzner offers the best price/performance ratio by a significant margin. European data centers (Germany, Finland) plus US East (Ashburn) and US West.

### Instance Sizing

Each database host needs enough RAM for the graph data (Memgraph and FalkorDB are in-memory) and enough CPU for batch processing. The extractor host needs CPU for XML parsing and network for RabbitMQ.

**Recommended instance per host: 4 vCPU / 16 GB RAM**

This accommodates in-memory databases (Memgraph, FalkorDB) for a representative dataset subset while keeping costs low. The full 20M+ record Discogs dataset may need 32GB for in-memory backends — start with a subset and scale up if needed.

### Pricing Comparison (4 vCPU / 16 GB RAM × 6 hosts)

| Provider | Instance Type | Per Host/mo | Per Host/hr | 6 Hosts/mo | 6 Hosts × 48hr |
|----------|--------------|-------------|-------------|------------|-----------------|
| **Hetzner** | CX43 (shared) | €9.49 | €0.015 | **€56.94** | **€4.32** |
| **Hetzner** | CPX31 (4 vCPU/8GB dedicated) | €16.49 | €0.027 | €98.94 | €7.78 |
| **Hetzner** | CCX23 (4 vCPU/16GB dedicated) | €24.49 | €0.039 | €146.94 | €11.23 |
| **Vultr** | Regular (4 vCPU/8GB) | $40.00 | $0.060 | $240.00 | $17.28 |
| **Vultr** | High Perf (4 vCPU/8GB) | $48.00 | $0.071 | $288.00 | $20.45 |
| **DigitalOcean** | Basic (4 vCPU/8GB) | ~$48.00 | ~$0.071 | ~$288.00 | ~$20.45 |
| **DigitalOcean** | Gen Purpose (4 vCPU/16GB) | ~$84.00 | ~$0.125 | ~$504.00 | ~$36.00 |

### Recommendation

**Use Hetzner CX43 (shared vCPU) for initial benchmarks.** At €0.015/hr per host, running all 6 hosts for a 48-hour benchmark window costs **under €5 total.** If shared vCPU introduces noise, upgrade to CCX23 (dedicated) at €11.23 for 48 hours — still extremely cheap.

**For a budget of under $20**, you can run the full benchmark suite on Hetzner dedicated instances for 2 days.

### Alternative Providers

| Provider | Strength | When to Use |
|----------|----------|-------------|
| **Hetzner** (recommended) | Cheapest by 3-5x, hourly billing, good perf | Default choice — best price/performance |
| **Vultr** | More regions (30+), bare metal options, good API | If you need US West Coast or APAC regions |
| **DigitalOcean** | Best developer UX, managed databases for comparison | If you want managed Neo4j/Redis for reference |

## Metrics Collection

### What to Measure During Import

| Metric | Collection Method | Frequency |
|--------|-------------------|-----------|
| Total import wall-clock time | Timestamp at start/end | Once |
| Per-batch import latency (ms) | Graphinator logs (already tracked) | Per batch |
| Batch throughput (records/sec) | Graphinator logs (already tracked) | Per batch |
| Per-entity-type import time | Graphinator logs (file_complete timestamps) | Per type |
| Queue depth over time | RabbitMQ management API | Every 10s |
| CPU usage (%) | `node_exporter` or `vmstat` | Every 5s |
| Memory usage (RSS, cache) | `node_exporter` or `/proc/meminfo` | Every 5s |
| Disk usage (bytes) | `df` + database-specific query | Every 30s |
| Disk I/O (read/write MB/s) | `iostat` or `node_exporter` | Every 5s |
| Network I/O (MB/s) | `node_exporter` | Every 5s |

### What to Measure Post-Import (Explore Benchmarks)

Run every query type used in the explore frontend against each database:

| Benchmark | Queries | Iterations | What It Tests |
|-----------|---------|------------|---------------|
| Autocomplete | 4 fulltext search queries (artist, label, genre, style) | 500 each | Search latency |
| Explore center-node | 4 queries (artist, genre, label, style) | 200 each | Aggregation + COUNT |
| Expand (shallow) | 12 queries (all entity+category combos) | 200 each | 1-hop traversal + pagination |
| Expand count | 12 count queries | 200 each | Traversal + aggregation |
| Node detail | 5 queries (artist, release, label, genre, style) | 200 each | Multi-hop + collect |
| Trends | 4 queries (by entity type) | 200 each | Year grouping + aggregation |
| User collection | 3 queries (collection, wantlist, stats) | 200 each | User-scoped traversal |
| Gap analysis | 3 queries (label gaps, artist gaps, master gaps) | 100 each | Exclusion pattern traversal |
| Recommendations | 1 query | 100 | Multi-hop + scoring |
| Point read | `MATCH (a:Artist {id: $id})` | 1000 | Index lookup baseline |
| Concurrent mixed | 4 readers + 1 writer | 60 seconds | Contention under load |

### Metrics Output Format

Each benchmark run produces a JSON file:

```json
{
  "backend": "neo4j",
  "host": "bench-neo4j.example.com",
  "instance_type": "hetzner-cx43",
  "dataset": "discogs-2026-03",
  "import_metrics": {
    "total_duration_sec": 3600,
    "artists": {"count": 8500000, "duration_sec": 450, "records_per_sec": 18888},
    "labels": {"count": 2100000, "duration_sec": 120, "records_per_sec": 17500},
    "masters": {"count": 2200000, "duration_sec": 300, "records_per_sec": 7333},
    "releases": {"count": 16000000, "duration_sec": 2700, "records_per_sec": 5925}
  },
  "system_metrics": {
    "peak_memory_mb": 12400,
    "peak_cpu_percent": 85,
    "disk_usage_mb": 8500,
    "avg_disk_io_mb_sec": 45
  },
  "benchmarks": {
    "autocomplete_artist": {"p50_ms": 2.1, "p95_ms": 5.3, "p99_ms": 12.1},
    "explore_center_artist": {"p50_ms": 8.4, "p95_ms": 22.1, "p99_ms": 45.0},
    "expand_releases_by_artist": {"p50_ms": 3.2, "p95_ms": 8.1, "p99_ms": 15.3}
  }
}
```

## Automated Deployment with Ansible

Ansible is the right tool here — agentless (SSH-only), simple YAML playbooks, good Hetzner/Vultr/DO modules for provisioning.

### Directory Structure

```
infra/
  ansible.cfg
  inventory/
    hosts.yml                    -- generated by provisioning playbook
  playbooks/
    provision.yml                -- create cloud instances
    setup-common.yml             -- common setup (Docker, monitoring, firewall)
    setup-extractor.yml          -- extractor + RabbitMQ host
    setup-neo4j.yml              -- Neo4j + graphinator[neo4j]
    setup-memgraph.yml           -- Memgraph + graphinator[memgraph]
    setup-age.yml                -- PostgreSQL+AGE + graphinator[age]
    setup-falkordb.yml           -- FalkorDB + graphinator[falkordb]
    setup-arangodb.yml           -- ArangoDB + graphinator[arangodb]
    run-import.yml               -- start extraction + monitor import
    run-benchmarks.yml           -- run post-import benchmarks
    collect-results.yml          -- gather results to local machine
    teardown.yml                 -- destroy all instances
  roles/
    common/                      -- Docker, monitoring agent, firewall
    extractor/                   -- Rust binary + RabbitMQ container
    graphinator/                 -- Python service + backend config
    neo4j/                       -- Neo4j container + schema init
    memgraph/                    -- Memgraph container + schema init
    age/                         -- PostgreSQL+AGE container + schema init
    falkordb/                    -- FalkorDB container + schema init
    arangodb/                    -- ArangoDB container + schema init
    benchmark/                   -- benchmark harness
  templates/
    docker-compose.extractor.yml.j2
    docker-compose.neo4j.yml.j2
    docker-compose.memgraph.yml.j2
    docker-compose.age.yml.j2
    docker-compose.falkordb.yml.j2
    docker-compose.arangodb.yml.j2
    metrics-collector.sh.j2      -- system metrics collection script
  scripts/
    provision-hetzner.sh         -- Hetzner CLI wrapper
    provision-vultr.sh           -- Vultr CLI wrapper
    run-all.sh                   -- end-to-end: provision → deploy → import → benchmark → collect → teardown
```

### Provisioning Playbook

```yaml
# infra/playbooks/provision.yml
---
- name: Provision benchmark infrastructure
  hosts: localhost
  vars:
    provider: hetzner  # or vultr, digitalocean
    instance_type: cx43
    region: nbg1       # Nuremberg
    ssh_key_name: benchmark-key
    hosts:
      - { name: bench-extractor, role: extractor }
      - { name: bench-neo4j, role: neo4j }
      - { name: bench-memgraph, role: memgraph }
      - { name: bench-age, role: age }
      - { name: bench-falkordb, role: falkordb }
      - { name: bench-arangodb, role: arangodb }

  tasks:
    - name: Create SSH key
      hetzner.hcloud.ssh_key:
        name: "{{ ssh_key_name }}"
        public_key: "{{ lookup('file', '~/.ssh/id_ed25519.pub') }}"
        state: present

    - name: Create servers
      hetzner.hcloud.server:
        name: "{{ item.name }}"
        server_type: "{{ instance_type }}"
        image: ubuntu-24.04
        location: "{{ region }}"
        ssh_keys: ["{{ ssh_key_name }}"]
        state: present
      loop: "{{ hosts }}"
      register: servers

    - name: Generate inventory
      template:
        src: ../templates/inventory.yml.j2
        dest: ../inventory/hosts.yml
```

### Common Setup Role

```yaml
# infra/roles/common/tasks/main.yml
---
- name: Update packages
  apt:
    update_cache: yes
    upgrade: dist

- name: Install Docker
  include_role:
    name: geerlingguy.docker

- name: Install monitoring tools
  apt:
    name: [sysstat, iotop, htop, jq, curl]
    state: present

- name: Deploy metrics collector script
  template:
    src: metrics-collector.sh.j2
    dest: /opt/benchmark/metrics-collector.sh
    mode: '0755'

- name: Configure firewall
  ufw:
    rule: allow
    port: "{{ item }}"
    proto: tcp
  loop:
    - '22'     # SSH
    - '5672'   # AMQP (extractor host only)
    - '15672'  # RabbitMQ management
    - '7687'   # Bolt (Neo4j, Memgraph)
    - '5432'   # PostgreSQL (AGE)
    - '6379'   # Redis (FalkorDB)
    - '8529'   # ArangoDB HTTP
```

### Database Host Playbook (Example: Neo4j)

```yaml
# infra/playbooks/setup-neo4j.yml
---
- name: Setup Neo4j benchmark host
  hosts: bench-neo4j
  become: yes
  roles:
    - common

  tasks:
    - name: Deploy docker-compose
      template:
        src: ../templates/docker-compose.neo4j.yml.j2
        dest: /opt/benchmark/docker-compose.yml

    - name: Copy graphinator code
      synchronize:
        src: "{{ playbook_dir }}/../../graphinator/"
        dest: /opt/benchmark/graphinator/

    - name: Copy common code
      synchronize:
        src: "{{ playbook_dir }}/../../common/"
        dest: /opt/benchmark/common/

    - name: Start services
      community.docker.docker_compose_v2:
        project_src: /opt/benchmark
        state: present

    - name: Run schema init
      community.docker.docker_container_exec:
        container: schema-init
        command: python neo4j_schema.py

    - name: Start metrics collection
      command: >
        nohup /opt/benchmark/metrics-collector.sh
        --output /opt/benchmark/results/system-metrics.jsonl
        --interval 5 &
```

### Import Playbook

```yaml
# infra/playbooks/run-import.yml
---
- name: Run data import
  hosts: bench-extractor
  tasks:
    - name: Record start timestamp
      set_fact:
        import_start: "{{ ansible_date_time.epoch }}"

    - name: Start extractor
      community.docker.docker_compose_v2:
        project_src: /opt/benchmark
        services: [extractor]
        state: present

    - name: Wait for extraction to complete
      command: >
        docker logs --tail 1 extractor 2>&1
      register: extractor_log
      until: "'All files processed' in extractor_log.stdout"
      retries: 360
      delay: 60  # Check every minute, timeout after 6 hours

    - name: Wait for all queues to drain
      uri:
        url: "http://localhost:15672/api/queues/%2F?columns=name,messages"
        user: guest
        password: guest
        return_content: yes
      register: queue_status
      until: >
        (queue_status.json | map(attribute='messages') | sum) == 0
      retries: 720
      delay: 30  # Check every 30s, timeout after 6 hours

- name: Collect import results
  hosts: all:!bench-extractor
  tasks:
    - name: Stop metrics collection
      command: pkill -f metrics-collector.sh
      ignore_errors: yes

    - name: Fetch results
      fetch:
        src: /opt/benchmark/results/
        dest: ./results/{{ inventory_hostname }}/
        flat: no
```

### Benchmark Playbook

```yaml
# infra/playbooks/run-benchmarks.yml
---
- name: Run explore benchmarks against all databases
  hosts: bench-extractor  # Controller host
  vars:
    databases:
      - { name: neo4j, host: "{{ hostvars['bench-neo4j'].ansible_host }}", port: 7687, protocol: bolt }
      - { name: memgraph, host: "{{ hostvars['bench-memgraph'].ansible_host }}", port: 7687, protocol: bolt }
      - { name: age, host: "{{ hostvars['bench-age'].ansible_host }}", port: 5432, protocol: postgresql }
      - { name: falkordb, host: "{{ hostvars['bench-falkordb'].ansible_host }}", port: 6379, protocol: redis }
      - { name: arangodb, host: "{{ hostvars['bench-arangodb'].ansible_host }}", port: 8529, protocol: http }

  tasks:
    - name: Run benchmark suite for each database
      command: >
        uv run python -m benchmarks.runner
        --backend {{ item.name }}
        --host {{ item.host }}:{{ item.port }}
        --output /opt/benchmark/results/{{ item.name }}_benchmark.json
        --iterations 200
        --warmup 10
      loop: "{{ databases }}"
      loop_control:
        pause: 30  # 30s pause between databases

    - name: Generate comparison report
      command: >
        uv run python -m benchmarks.compare
        /opt/benchmark/results/*_benchmark.json
        --output /opt/benchmark/results/comparison.md

    - name: Fetch all results
      fetch:
        src: /opt/benchmark/results/
        dest: ./results/
        flat: no
```

### Teardown Playbook

```yaml
# infra/playbooks/teardown.yml
---
- name: Destroy all benchmark infrastructure
  hosts: localhost
  vars:
    hosts:
      - bench-extractor
      - bench-neo4j
      - bench-memgraph
      - bench-age
      - bench-falkordb
      - bench-arangodb

  tasks:
    - name: Destroy servers
      hetzner.hcloud.server:
        name: "{{ item }}"
        state: absent
      loop: "{{ hosts }}"

    - name: Remove SSH key
      hetzner.hcloud.ssh_key:
        name: benchmark-key
        state: absent
```

### End-to-End Script

```bash
#!/usr/bin/env bash
# infra/scripts/run-all.sh
set -euo pipefail

echo "=== Provisioning infrastructure ==="
ansible-playbook playbooks/provision.yml

echo "=== Setting up all hosts ==="
ansible-playbook playbooks/setup-common.yml
ansible-playbook playbooks/setup-extractor.yml
ansible-playbook playbooks/setup-neo4j.yml
ansible-playbook playbooks/setup-memgraph.yml
ansible-playbook playbooks/setup-age.yml
ansible-playbook playbooks/setup-falkordb.yml
ansible-playbook playbooks/setup-arangodb.yml

echo "=== Running data import ==="
ansible-playbook playbooks/run-import.yml

echo "=== Running benchmarks ==="
ansible-playbook playbooks/run-benchmarks.yml

echo "=== Collecting results ==="
ansible-playbook playbooks/collect-results.yml

echo "=== Results saved to ./results/ ==="
echo "=== Review results before tearing down ==="
read -p "Tear down infrastructure? [y/N] " confirm
if [[ "$confirm" == "y" ]]; then
    ansible-playbook playbooks/teardown.yml
fi
```

## System Metrics Collector

A lightweight script that runs on each database host, collecting system metrics to a JSONL file:

```bash
#!/usr/bin/env bash
# infra/templates/metrics-collector.sh.j2
OUTPUT="${1:---output /opt/benchmark/results/system-metrics.jsonl}"
INTERVAL="${2:-5}"

while true; do
    TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    CPU=$(grep 'cpu ' /proc/stat | awk '{u=$2+$4; t=$2+$4+$5; printf "%.1f", u/t*100}')
    MEM_TOTAL=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
    MEM_AVAIL=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
    MEM_USED=$((MEM_TOTAL - MEM_AVAIL))
    DISK=$(df /opt/benchmark --output=used -B1 | tail -1 | tr -d ' ')
    IO_READ=$(cat /proc/diskstats | awk '{r+=$6} END {print r}')
    IO_WRITE=$(cat /proc/diskstats | awk '{w+=$10} END {print w}')

    echo "{\"ts\":\"$TIMESTAMP\",\"cpu\":$CPU,\"mem_used_kb\":$MEM_USED,\"mem_total_kb\":$MEM_TOTAL,\"disk_bytes\":$DISK,\"io_read_sectors\":$IO_READ,\"io_write_sectors\":$IO_WRITE}" >> "$OUTPUT"

    sleep "$INTERVAL"
done
```

## Extractor Modifications

### Fan-Out Exchange Strategy

Modify the extractor to use a **single fanout exchange**. Each graphinator variant binds its own queues to this exchange. RabbitMQ handles the message duplication natively.

```rust
// extractor/src/message_queue.rs — benchmark mode
const BENCHMARK_EXCHANGE: &str = "bench-fanout";

pub async fn setup_benchmark_exchange(&self) -> Result<()> {
    self.channel
        .exchange_declare(
            BENCHMARK_EXCHANGE.into(),
            ExchangeKind::Fanout,  // Fan out to all bound queues
            ExchangeDeclareOptions { durable: true, ..Default::default() },
            FieldTable::default(),
        )
        .await?;
    Ok(())
}

pub async fn publish_benchmark(&self, message: Message, data_type: DataType) -> Result<()> {
    // Publish once — RabbitMQ copies to all bound queues
    self.channel
        .basic_publish(
            BENCHMARK_EXCHANGE.into(),
            data_type.routing_key().into(),  // Routing key still used for queue binding
            BasicPublishOptions::default(),
            &serde_json::to_vec(&message)?,
            BasicProperties::default().with_delivery_mode(2),
        )
        .await?;
    Ok(())
}
```

Each graphinator instance binds to the fanout exchange with its own queue prefix:

```python
# Graphinator on bench-neo4j host
AMQP_QUEUE_PREFIX = os.environ.get("AMQP_QUEUE_PREFIX", "bench-neo4j-graphinator")
# Queues: bench-neo4j-graphinator-artists, bench-neo4j-graphinator-labels, etc.
```

### Configuration

The extractor needs a single new environment variable:

```bash
BENCHMARK_MODE=true        # Use fanout exchange instead of topic
RABBITMQ_URL=amqp://guest:guest@bench-extractor:5672
```

Each graphinator needs:

```bash
AMQP_QUEUE_PREFIX=bench-{backend}-graphinator   # e.g., bench-neo4j-graphinator
GRAPH_BACKEND={backend}                          # e.g., neo4j, memgraph, age, falkordb, arangodb
RABBITMQ_URL=amqp://guest:guest@bench-extractor:5672
```

## Cost Estimates

### Scenario 1: Quick Benchmark (Subset — 1M records, ~8 hours)

| Provider | Instance | Count | Hours | Cost |
|----------|----------|-------|-------|------|
| **Hetzner CX43** | 4 vCPU / 16GB | 6 | 8 | **€0.72** |
| Vultr Regular | 4 vCPU / 8GB | 6 | 8 | $2.88 |
| DigitalOcean Basic | 4 vCPU / 8GB | 6 | 8 | ~$3.41 |

### Scenario 2: Full Benchmark (Full dataset — 20M+ records, ~48 hours)

| Provider | Instance | Count | Hours | Cost |
|----------|----------|-------|-------|------|
| **Hetzner CCX23** | 4 vCPU / 16GB dedicated | 6 | 48 | **€11.23** |
| **Hetzner CX43** | 4 vCPU / 16GB shared | 6 | 48 | **€4.32** |
| Vultr High Perf | 4 vCPU / 8GB | 6 | 48 | $20.45 |
| DigitalOcean GP | 4 vCPU / 16GB | 6 | 48 | ~$36.00 |

### Scenario 3: Full Benchmark with 32GB (for in-memory DBs)

| Provider | Instance | Count | Hours | Cost |
|----------|----------|-------|-------|------|
| **Hetzner CCX33** | 8 vCPU / 32GB dedicated | 6 | 48 | **€22.34** |
| Vultr Optimized | 8 vCPU / 32GB | 6 | 48 | $102.82 |

**Bottom line:** A full benchmark on Hetzner costs €5–22 depending on instance tier. Start with CX43 (shared) and upgrade only if CPU contention introduces noise.

### Additional Costs

| Item | Cost | Notes |
|------|------|-------|
| Hetzner network | Free | 20TB included per server |
| Vultr network | Free | First 1–2TB included |
| DO network | Free | First 1TB included |
| Discogs data download | Free | Public S3 bucket |
| DNS/floating IPs | Not needed | Use IP addresses directly |

## Prerequisites

### Local Machine Setup

```bash
# Install Ansible + Hetzner collection
uv tool install ansible-core
ansible-galaxy collection install hetzner.hcloud community.docker
pip install hcloud  # Hetzner API client for Ansible

# Set Hetzner API token
export HCLOUD_TOKEN="your-token-here"  # From Hetzner Cloud Console

# Generate SSH key (if needed)
ssh-keygen -t ed25519 -f ~/.ssh/benchmark-key -N ""
```

### Hetzner Account Setup

1. Create account at [console.hetzner.cloud](https://console.hetzner.cloud)
2. Create a project (e.g., "discogsography-benchmark")
3. Generate API token (Read/Write) under Security > API Tokens
4. Set `HCLOUD_TOKEN` environment variable

## Work Items

- [ ] Create `infra/` directory structure with Ansible playbooks and roles
- [ ] Implement fanout exchange mode in extractor (`BENCHMARK_MODE` env var)
- [ ] Create graphinator backend variants (or parameterize existing graphinator with `GRAPH_BACKEND`)
- [ ] Implement graph backend abstraction layer (see [shared-pre-work.md](shared-pre-work.md))
- [ ] Implement each backend: neo4j, memgraph, age, falkordb, arangodb
- [ ] Create Docker Compose templates for each database host
- [ ] Create system metrics collector script
- [ ] Create benchmark harness (see [shared-pre-work.md](shared-pre-work.md))
- [ ] Write provisioning playbook (Hetzner, with Vultr alternative)
- [ ] Write setup playbooks for each host role
- [ ] Write import orchestration playbook
- [ ] Write benchmark orchestration playbook
- [ ] Write results collection playbook
- [ ] Write teardown playbook
- [ ] Create `run-all.sh` end-to-end script
- [ ] Test with 2 hosts first (extractor + neo4j) before scaling to all 6
- [ ] Create Hetzner account and generate API token
- [ ] Run Scenario 1 (subset) first to validate the pipeline
- [ ] Run Scenario 2 (full dataset) if Scenario 1 succeeds
