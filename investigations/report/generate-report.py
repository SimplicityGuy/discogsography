#!/usr/bin/env python3
"""Generate normalized benchmark analysis report with charts.

Reads raw benchmark results and calibration data, normalizes to a baseline,
and produces charts for the investigation report.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


# --- Paths ---
RESULTS_DIR = Path(__file__).parent.parent / "results"
IMAGES_DIR = Path(__file__).parent / "images"
IMAGES_DIR.mkdir(exist_ok=True)

# --- Style ---
plt.rcParams.update(
    {
        "figure.figsize": (10, 6),
        "figure.dpi": 150,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "legend.fontsize": 10,
        "figure.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.3,
    }
)

DB_COLORS = {
    "neo4j": "#4C8BF5",
    "falkordb": "#FF6B35",
    "arangodb": "#7B2D8E",
}
DB_LABELS = {
    "neo4j": "Neo4j",
    "falkordb": "FalkorDB",
    "arangodb": "ArangoDB",
}
DATABASES = ["neo4j", "falkordb", "arangodb"]


def load_json(path: Path) -> dict:
    with path.open() as f:
        result: dict = json.load(f)
    return result


def find_benchmark_file(db: str, scale: str) -> Path | None:
    """Find the benchmark result file for a given db and scale."""
    for p in RESULTS_DIR.glob(f"{db}-{scale}-*.json"):
        if "calibration" not in p.name:
            return p
    return None


def compute_calibration_factor(baseline: dict, db_cal: dict) -> float:
    """Compute a composite hardware normalization factor.

    Factor > 1 means DB ran on slower hardware (results should be improved).
    Factor < 1 means DB ran on faster hardware (results should be penalized).

    We use a weighted geometric mean of per-metric ratios:
    - CPU single-thread (50%): dominates query latency
    - Memory read bandwidth (20%): affects traversals and aggregations
    - Disk random read IOPS (20%): affects cold reads
    - Python sort (10%): general runtime overhead
    """
    bb = baseline["benchmarks"]
    db = db_cal["benchmarks"]

    ratios = {
        "cpu_st": bb["cpu_single_thread"]["ops_per_sec"] / db["cpu_single_thread"]["ops_per_sec"],
        "mem_read": bb["memory_bandwidth"]["read_mb_per_sec"] / db["memory_bandwidth"]["read_mb_per_sec"],
        "disk_iops": bb["disk_random_read"]["iops"] / db["disk_random_read"]["iops"],
        "python": bb["python_sort"]["sorts_per_sec"] / db["python_sort"]["sorts_per_sec"],
    }
    weights = {"cpu_st": 0.50, "mem_read": 0.20, "disk_iops": 0.20, "python": 0.10}

    log_sum = sum(weights[k] * np.log(ratios[k]) for k in ratios)
    return float(np.exp(log_sum))


def normalize_benchmarks(benchmarks: dict, factor: float) -> dict:
    """Apply calibration factor to benchmark results.

    Latency metrics are multiplied by factor (slower HW -> lower normalized latency).
    Throughput metrics are divided by factor (slower HW -> higher normalized throughput).
    """
    normalized = {}
    for name, data in benchmarks.items():
        entry = dict(data)
        if name == "concurrent_mixed":
            # Special structure
            for k in ["read_p50_ms", "read_p95_ms"]:
                if k in entry:
                    entry[k] = entry[k] * factor
            for k in ["read_throughput_ops_sec"]:
                if k in entry:
                    entry[k] = entry[k] / factor
            for k in ["write_p50_ms", "write_p95_ms"]:
                if k in entry:
                    entry[k] = entry[k] * factor
            for k in ["write_throughput_ops_sec"]:
                if k in entry:
                    entry[k] = entry[k] / factor
        else:
            for k in ["p50_ms", "p95_ms", "p99_ms", "mean_ms", "min_ms", "max_ms"]:
                if k in entry:
                    entry[k] = entry[k] * factor
            if "throughput_ops_sec" in entry:
                entry["throughput_ops_sec"] = entry["throughput_ops_sec"] / factor
        normalized[name] = entry
    return normalized


def normalize_insertion(insertion: dict, factor: float) -> dict:
    """Normalize insertion metrics."""
    normalized = {}
    for name, data in insertion.items():
        if name == "total_duration_sec":
            normalized[name] = data * factor
            continue
        entry = dict(data)
        if "duration_sec" in entry:
            entry["duration_sec"] = entry["duration_sec"] * factor
        if "records_per_sec" in entry:
            entry["records_per_sec"] = entry["records_per_sec"] / factor
        normalized[name] = entry
    return normalized


# ────────────────────────────────────────────
# Load data
# ────────────────────────────────────────────

baseline = load_json(RESULTS_DIR / "baseline-calibration.json")

calibrations = {}
raw_results: dict[str, dict[str, dict]] = {}
factors = {}
norm_results: dict[str, dict[str, dict]] = {}

for db in DATABASES:
    calibrations[db] = load_json(RESULTS_DIR / f"{db}-calibration.json")
    factors[db] = compute_calibration_factor(baseline, calibrations[db])
    raw_results[db] = {}
    norm_results[db] = {}
    for scale in ["small", "large"]:
        f = find_benchmark_file(db, scale)
        if f:
            data = load_json(f)
            raw_results[db][scale] = data
            norm_results[db][scale] = {
                "backend": db,
                "scale": scale,
                "benchmarks": normalize_benchmarks(data["benchmarks"], factors[db]),
                "insertion_metrics": normalize_insertion(data["insertion_metrics"], factors[db]),
            }

# Print calibration factors
print("=== Calibration Factors ===")
for db in DATABASES:
    print(f"  {DB_LABELS[db]}: {factors[db]:.4f}")
print()


# ────────────────────────────────────────────
# Chart helpers
# ────────────────────────────────────────────


def save(fig: plt.Figure, name: str) -> None:
    fig.tight_layout()
    fig.savefig(IMAGES_DIR / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {name}.png")


# ────────────────────────────────────────────
# Chart 1: P50 Latency comparison (small + large)
# ────────────────────────────────────────────

workloads_latency = ["point_read", "graph_traversal", "fulltext_search", "aggregation", "batch_write_nodes", "batch_write_full_tx"]
wl_labels = ["Point Read", "Graph\nTraversal", "Fulltext\nSearch", "Aggregation", "Batch Write\nNodes", "Batch Write\nFull Tx"]

for scale in ["small", "large"]:
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(workloads_latency))
    width = 0.25

    for i, db in enumerate(DATABASES):
        vals = [norm_results[db][scale]["benchmarks"][w]["p50_ms"] for w in workloads_latency]
        bars = ax.bar(x + i * width, vals, width, label=DB_LABELS[db], color=DB_COLORS[db], edgecolor="white", linewidth=0.5)
        for bar, val in zip(bars, vals, strict=True):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1, f"{val:.1f}", ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("Workload")
    ax.set_ylabel("P50 Latency (ms) — lower is better")
    ax.set_title(f"Normalized P50 Latency — {scale.title()} Scale ({('135K' if scale == 'small' else '1.35M')} nodes)")
    ax.set_xticks(x + width)
    ax.set_xticklabels(wl_labels)
    ax.legend()
    ax.set_ylim(bottom=0)
    save(fig, f"p50-latency-{scale}")


# ────────────────────────────────────────────
# Chart 2: Throughput comparison
# ────────────────────────────────────────────

for scale in ["small", "large"]:
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(workloads_latency))
    width = 0.25

    for i, db in enumerate(DATABASES):
        vals = [norm_results[db][scale]["benchmarks"][w]["throughput_ops_sec"] for w in workloads_latency]
        bars = ax.bar(x + i * width, vals, width, label=DB_LABELS[db], color=DB_COLORS[db], edgecolor="white", linewidth=0.5)

    ax.set_xlabel("Workload")
    ax.set_ylabel("Throughput (ops/sec) — higher is better")
    ax.set_title(f"Normalized Throughput — {scale.title()} Scale ({('135K' if scale == 'small' else '1.35M')} nodes)")
    ax.set_xticks(x + width)
    ax.set_xticklabels(wl_labels)
    ax.legend()
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(ticker.ScalarFormatter())
    ax.yaxis.get_major_formatter().set_scientific(False)
    save(fig, f"throughput-{scale}")


# ────────────────────────────────────────────
# Chart 3: P95 tail latency comparison
# ────────────────────────────────────────────

for scale in ["small", "large"]:
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(workloads_latency))
    width = 0.25

    for i, db in enumerate(DATABASES):
        vals = [norm_results[db][scale]["benchmarks"][w]["p95_ms"] for w in workloads_latency]
        bars = ax.bar(x + i * width, vals, width, label=DB_LABELS[db], color=DB_COLORS[db], edgecolor="white", linewidth=0.5)
        for bar, val in zip(bars, vals, strict=True):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1, f"{val:.1f}", ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("Workload")
    ax.set_ylabel("P95 Latency (ms) — lower is better")
    ax.set_title(f"Normalized P95 Tail Latency — {scale.title()} Scale ({('135K' if scale == 'small' else '1.35M')} nodes)")
    ax.set_xticks(x + width)
    ax.set_xticklabels(wl_labels)
    ax.legend()
    ax.set_ylim(bottom=0)
    save(fig, f"p95-latency-{scale}")


# ────────────────────────────────────────────
# Chart 4: Data ingestion throughput
# ────────────────────────────────────────────

insertion_types = ["artists", "labels", "masters", "releases"]
rel_types = ["by_rels", "on_rels", "derived_from_rels", "is_rels"]
insert_labels = ["Artists", "Labels", "Masters", "Releases"]
rel_labels = ["BY", "ON", "DERIVED\nFROM", "IS\n(genre+style)"]

for scale in ["small", "large"]:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Nodes
    x = np.arange(len(insertion_types))
    width = 0.25
    for i, db in enumerate(DATABASES):
        vals = [norm_results[db][scale]["insertion_metrics"][t]["records_per_sec"] for t in insertion_types]
        ax1.bar(x + i * width, vals, width, label=DB_LABELS[db], color=DB_COLORS[db], edgecolor="white", linewidth=0.5)
    ax1.set_xlabel("Node Type")
    ax1.set_ylabel("Records/sec — higher is better")
    ax1.set_title(f"Node Insertion — {scale.title()} Scale")
    ax1.set_xticks(x + width)
    ax1.set_xticklabels(insert_labels)
    ax1.legend()

    # Relationships
    x = np.arange(len(rel_types))
    for i, db in enumerate(DATABASES):
        vals = [norm_results[db][scale]["insertion_metrics"][t]["records_per_sec"] for t in rel_types]
        ax2.bar(x + i * width, vals, width, label=DB_LABELS[db], color=DB_COLORS[db], edgecolor="white", linewidth=0.5)
    ax2.set_xlabel("Relationship Type")
    ax2.set_ylabel("Records/sec — higher is better")
    ax2.set_title(f"Relationship Insertion — {scale.title()} Scale")
    ax2.set_xticks(x + width)
    ax2.set_xticklabels(rel_labels)
    ax2.legend()

    save(fig, f"insertion-throughput-{scale}")


# ────────────────────────────────────────────
# Chart 5: Total ingestion time
# ────────────────────────────────────────────

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))

for ax, scale in [(ax1, "small"), (ax2, "large")]:
    vals = [norm_results[db][scale]["insertion_metrics"]["total_duration_sec"] for db in DATABASES]
    colors = [DB_COLORS[db] for db in DATABASES]
    labels = [DB_LABELS[db] for db in DATABASES]
    bars = ax.bar(labels, vals, color=colors, edgecolor="white", linewidth=0.5)
    for bar, val in zip(bars, vals, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{val:.0f}s", ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Total Duration (seconds) — lower is better")
    ax.set_title(
        f"Total Ingestion Time — {scale.title()} Scale\n({('135K' if scale == 'small' else '1.35M')} nodes, {('540K' if scale == 'small' else '5.4M')} rels)"
    )
    ax.set_ylim(bottom=0)

save(fig, "total-ingestion-time")


# ────────────────────────────────────────────
# Chart 6: Concurrent mixed workload
# ────────────────────────────────────────────

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

for ax, scale in [(ax1, "small"), (ax2, "large")]:
    dbs_with_write = []
    read_tp = []
    write_tp = []
    read_only_dbs = []
    read_only_tp = []

    for db in DATABASES:
        bm = norm_results[db][scale]["benchmarks"]["concurrent_mixed"]
        if "write_throughput_ops_sec" in bm:
            dbs_with_write.append(DB_LABELS[db])
            read_tp.append(bm["read_throughput_ops_sec"])
            write_tp.append(bm["write_throughput_ops_sec"])
        else:
            read_only_dbs.append(DB_LABELS[db])
            read_only_tp.append(bm["read_throughput_ops_sec"])

    x = np.arange(len(dbs_with_write) + len(read_only_dbs))
    all_labels = dbs_with_write + read_only_dbs
    all_read = read_tp + read_only_tp
    all_write = write_tp + [0] * len(read_only_dbs)

    width = 0.35
    ax.bar(x - width / 2, all_read, width, label="Read ops/sec", color="#4CAF50")
    ax.bar(x + width / 2, all_write, width, label="Write ops/sec", color="#FF5722")

    ax.set_ylabel("Throughput (ops/sec)")
    ax.set_title(f"Concurrent Mixed Workload — {scale.title()} Scale\n(4 readers + 2 writers, 30s)")
    ax.set_xticks(x)
    ax.set_xticklabels(all_labels)
    ax.legend()

    # Add note for missing write data
    for i, db_label in enumerate(all_labels):
        if db_label in read_only_dbs:
            ax.annotate("no write\ndata*", (x[i] + width / 2, 5), ha="center", fontsize=8, color="gray")

save(fig, "concurrent-mixed")


# ────────────────────────────────────────────
# Chart 7: Scale factor analysis (small→large)
# ────────────────────────────────────────────

read_workloads = ["point_read", "graph_traversal", "fulltext_search", "aggregation"]
read_labels_short = ["Point Read", "Graph Traversal", "Fulltext Search", "Aggregation"]

fig, ax = plt.subplots(figsize=(10, 6))
x = np.arange(len(read_workloads))
width = 0.25

for i, db in enumerate(DATABASES):
    ratios = []
    for w in read_workloads:
        small_p50 = norm_results[db]["small"]["benchmarks"][w]["p50_ms"]
        large_p50 = norm_results[db]["large"]["benchmarks"][w]["p50_ms"]
        ratios.append(large_p50 / small_p50)
    ax.bar(x + i * width, ratios, width, label=DB_LABELS[db], color=DB_COLORS[db], edgecolor="white", linewidth=0.5)

ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5, label="No degradation")
ax.set_xlabel("Workload")
ax.set_ylabel("P50 Ratio (large / small) — closer to 1.0 is better")
ax.set_title("Scalability: P50 Latency Degradation from Small (135K) to Large (1.35M)")
ax.set_xticks(x + width)
ax.set_xticklabels(read_labels_short)
ax.legend()
ax.set_ylim(bottom=0)
save(fig, "scalability-ratio")


# ────────────────────────────────────────────
# Chart 8: Radar/Spider chart - overall comparison
# ────────────────────────────────────────────

# Normalize each metric to 0-1 where 1 = best
categories = [
    "Point Read\nLatency",
    "Graph Traversal\nLatency",
    "Fulltext Search\nLatency",
    "Aggregation\nLatency",
    "Batch Write\nLatency",
    "Ingestion\nSpeed",
    "Concurrent\nRead Throughput",
    "Scalability",
]


def compute_scores(db: str) -> list[float]:
    """Compute 0-1 scores for radar chart (1 = best across DBs)."""
    scores = []
    # Latency scores (lower is better - invert)
    for w in ["point_read", "graph_traversal", "fulltext_search", "aggregation", "batch_write_nodes"]:
        vals = {d: norm_results[d]["large"]["benchmarks"][w]["p50_ms"] for d in DATABASES}
        best = min(vals.values())
        scores.append(best / vals[db])

    # Ingestion speed (lower total time is better)
    vals = {d: norm_results[d]["large"]["insertion_metrics"]["total_duration_sec"] for d in DATABASES}
    best = min(vals.values())
    scores.append(best / vals[db])

    # Concurrent read throughput (higher is better)
    vals = {d: norm_results[d]["large"]["benchmarks"]["concurrent_mixed"]["read_throughput_ops_sec"] for d in DATABASES}
    best = max(vals.values())
    scores.append(vals[db] / best)

    # Scalability (lower p50 ratio = better)
    ratios = {}
    for d in DATABASES:
        r = (
            sum(
                norm_results[d]["large"]["benchmarks"][w]["p50_ms"] / norm_results[d]["small"]["benchmarks"][w]["p50_ms"]
                for w in ["point_read", "graph_traversal", "fulltext_search", "aggregation"]
            )
            / 4
        )
        ratios[d] = r
    best = min(ratios.values())
    scores.append(best / ratios[db])

    return scores


fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"polar": True})
angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
angles += angles[:1]

for db in DATABASES:
    scores = compute_scores(db)
    scores += scores[:1]
    ax.plot(angles, scores, "o-", linewidth=2, label=DB_LABELS[db], color=DB_COLORS[db])
    ax.fill(angles, scores, alpha=0.1, color=DB_COLORS[db])

ax.set_xticks(angles[:-1])
ax.set_xticklabels(categories, size=9)
ax.set_ylim(0, 1.1)
ax.set_title("Overall Comparison — Large Scale (normalized, 1.0 = best)", pad=20)
ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
save(fig, "radar-comparison")


# ────────────────────────────────────────────
# Chart 9: Calibration hardware comparison
# ────────────────────────────────────────────

fig, axes = plt.subplots(2, 2, figsize=(12, 8))

cal_metrics = [
    ("cpu_single_thread", "ops_per_sec", "CPU Single-Thread (ops/sec)"),
    ("memory_bandwidth", "read_mb_per_sec", "Memory Read Bandwidth (MB/sec)"),
    ("disk_random_read", "iops", "Disk Random Read (IOPS)"),
    ("python_sort", "sorts_per_sec", "Python Sort (sorts/sec)"),
]

all_cals = {"Baseline": baseline}
for db in DATABASES:
    all_cals[DB_LABELS[db]] = calibrations[db]

for idx, (metric, key, title) in enumerate(cal_metrics):
    ax = axes[idx // 2][idx % 2]
    labels = list(all_cals.keys())
    vals = [all_cals[label]["benchmarks"][metric][key] for label in labels]
    colors = ["#888888"] + [DB_COLORS[db] for db in DATABASES]
    ax.bar(labels, vals, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_title(title)
    ax.set_ylabel(key.replace("_", " "))

fig.suptitle("Hardware Calibration Comparison", fontsize=14, fontweight="bold")
save(fig, "calibration-comparison")


# ────────────────────────────────────────────
# Output normalized data tables for the report
# ────────────────────────────────────────────

print("\n=== Normalized P50 Latency (ms) — Large Scale ===")
print(f"{'Workload':<25} {'Neo4j':>10} {'FalkorDB':>10} {'ArangoDB':>10}")
print("-" * 55)
_wl_names = ["Point Read", "Graph Traversal", "Fulltext Search", "Aggregation", "Batch Write Nodes", "Batch Write Full Tx"]
for w, label in zip(workloads_latency, _wl_names, strict=True):
    row = [norm_results[db]["large"]["benchmarks"][w]["p50_ms"] for db in DATABASES]
    print(f"{label:<25} {row[0]:>10.2f} {row[1]:>10.2f} {row[2]:>10.2f}")

print("\n=== Normalized Throughput (ops/sec) — Large Scale ===")
print(f"{'Workload':<25} {'Neo4j':>10} {'FalkorDB':>10} {'ArangoDB':>10}")
print("-" * 55)
for w, label in zip(workloads_latency, _wl_names, strict=True):
    row = [norm_results[db]["large"]["benchmarks"][w]["throughput_ops_sec"] for db in DATABASES]
    print(f"{label:<25} {row[0]:>10.1f} {row[1]:>10.1f} {row[2]:>10.1f}")

print("\n=== Normalized Total Ingestion Time (seconds) ===")
print(f"{'Scale':<10} {'Neo4j':>10} {'FalkorDB':>10} {'ArangoDB':>10}")
print("-" * 40)
for scale in ["small", "large"]:
    row = [norm_results[db][scale]["insertion_metrics"]["total_duration_sec"] for db in DATABASES]
    print(f"{scale:<10} {row[0]:>10.1f} {row[1]:>10.1f} {row[2]:>10.1f}")

print("\n=== Calibration Factors (baseline / db_hardware) ===")
for db in DATABASES:
    bb = baseline["benchmarks"]
    dc = calibrations[db]["benchmarks"]
    print(f"\n{DB_LABELS[db]} (composite factor: {factors[db]:.4f}):")
    print(
        f"  CPU single:  baseline={bb['cpu_single_thread']['ops_per_sec']:.0f}  "
        f"db={dc['cpu_single_thread']['ops_per_sec']:.0f}  "
        f"ratio={bb['cpu_single_thread']['ops_per_sec'] / dc['cpu_single_thread']['ops_per_sec']:.4f}"
    )
    print(
        f"  Mem read:    baseline={bb['memory_bandwidth']['read_mb_per_sec']:.0f}  "
        f"db={dc['memory_bandwidth']['read_mb_per_sec']:.0f}  "
        f"ratio={bb['memory_bandwidth']['read_mb_per_sec'] / dc['memory_bandwidth']['read_mb_per_sec']:.4f}"
    )
    print(
        f"  Disk IOPS:   baseline={bb['disk_random_read']['iops']:.0f}  "
        f"db={dc['disk_random_read']['iops']:.0f}  "
        f"ratio={bb['disk_random_read']['iops'] / dc['disk_random_read']['iops']:.4f}"
    )

print("\nDone!")
