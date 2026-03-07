"""Hardware calibration for scaling benchmark results across environments.

Runs portable micro-benchmarks that stress the same dimensions as the database
workloads (CPU, memory, sequential I/O, random I/O). Compare calibration output
from the Hetzner CX53 benchmark hosts against your local machine to derive
per-dimension scaling factors.

Usage:
    # Run calibration on your machine
    uv run python docs/investigations/calibration/calibrate.py run [--output calibration.json]

    # Scale benchmark results using two calibration files
    uv run python docs/investigations/calibration/calibrate.py scale \
      --baseline hetzner-calibration.json \
      --local my-calibration.json \
      --benchmark-results docs/investigations/calibration/results/neo4j_large_2026-03-10.json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess  # nosec B404
import sys
import tempfile
import time
from typing import Any


# ---------------------------------------------------------------------------
# Calibration benchmarks
# ---------------------------------------------------------------------------


def _cpu_single_thread(duration_sec: float = 5.0) -> dict[str, Any]:
    """SHA-256 hashing throughput on a single core."""
    data = os.urandom(4096)
    count = 0
    start = time.perf_counter()
    while time.perf_counter() - start < duration_sec:
        hashlib.sha256(data).digest()
        count += 1
    elapsed = time.perf_counter() - start
    return {
        "test": "cpu_single_thread_sha256",
        "ops": count,
        "duration_sec": round(elapsed, 3),
        "ops_per_sec": round(count / elapsed, 1),
    }


def _cpu_multi_thread(duration_sec: float = 5.0) -> dict[str, Any]:
    """SHA-256 hashing throughput across all cores."""
    import concurrent.futures

    cores = os.cpu_count() or 1
    data = os.urandom(4096)

    def worker() -> int:
        n = 0
        deadline = time.perf_counter() + duration_sec
        while time.perf_counter() < deadline:
            hashlib.sha256(data).digest()
            n += 1
        return n

    with concurrent.futures.ThreadPoolExecutor(max_workers=cores) as pool:
        start = time.perf_counter()
        futures = [pool.submit(worker) for _ in range(cores)]
        total = sum(f.result() for f in futures)
        elapsed = time.perf_counter() - start

    return {
        "test": "cpu_multi_thread_sha256",
        "cores": cores,
        "ops": total,
        "duration_sec": round(elapsed, 3),
        "ops_per_sec": round(total / elapsed, 1),
    }


def _memory_bandwidth() -> dict[str, Any]:
    """Sequential memory read/write throughput (64 MB buffer, 5 iterations)."""
    buf_size = 64 * 1024 * 1024  # 64 MB
    iterations = 5

    # Write
    write_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        buf = bytearray(buf_size)
        for i in range(0, buf_size, 4096):
            buf[i] = 0xFF
        write_times.append(time.perf_counter() - start)

    # Read
    buf = bytearray(buf_size)
    read_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        total = 0
        for i in range(0, buf_size, 4096):
            total += buf[i]
        read_times.append(time.perf_counter() - start)

    avg_write = statistics.mean(write_times)
    avg_read = statistics.mean(read_times)
    return {
        "test": "memory_bandwidth_64mb",
        "write_mb_per_sec": round(buf_size / avg_write / 1024 / 1024, 1),
        "read_mb_per_sec": round(buf_size / avg_read / 1024 / 1024, 1),
    }


def _disk_sequential_write(size_mb: int = 256) -> dict[str, Any]:
    """Sequential write throughput using direct I/O (or buffered with fsync)."""
    block_size = 1024 * 1024  # 1 MB
    blocks = size_mb
    data = os.urandom(block_size)

    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = Path(f.name)

    try:
        start = time.perf_counter()
        with path.open("wb") as f:
            for _ in range(blocks):
                f.write(data)
            f.flush()
            os.fsync(f.fileno())
        elapsed = time.perf_counter() - start
    finally:
        path.unlink()

    return {
        "test": "disk_sequential_write",
        "size_mb": size_mb,
        "duration_sec": round(elapsed, 3),
        "mb_per_sec": round(size_mb / elapsed, 1),
    }


def _disk_sequential_read(size_mb: int = 256) -> dict[str, Any]:
    """Sequential read throughput."""
    block_size = 1024 * 1024
    blocks = size_mb
    data = os.urandom(block_size)

    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = Path(f.name)
        for _ in range(blocks):
            f.write(data)

    try:
        # Drop caches if possible (Linux only, non-fatal if it fails)
        with contextlib.suppress(PermissionError, FileNotFoundError):
            Path("/proc/sys/vm/drop_caches").write_text("3")

        start = time.perf_counter()
        with path.open("rb") as f:
            while f.read(block_size):
                pass
        elapsed = time.perf_counter() - start
    finally:
        path.unlink()

    return {
        "test": "disk_sequential_read",
        "size_mb": size_mb,
        "duration_sec": round(elapsed, 3),
        "mb_per_sec": round(size_mb / elapsed, 1),
    }


def _disk_random_iops(file_size_mb: int = 128, duration_sec: float = 5.0) -> dict[str, Any]:
    """Random 4 KB read IOPS (simulates index lookups)."""
    block_size = 4096
    data = os.urandom(file_size_mb * 1024 * 1024)

    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = Path(f.name)
        f.write(data)

    max_offset = len(data) - block_size
    try:
        count = 0
        with path.open("rb") as f:
            start = time.perf_counter()
            while time.perf_counter() - start < duration_sec:
                offset = random.randint(0, max_offset) & ~(block_size - 1)  # nosec B311
                f.seek(offset)
                f.read(block_size)
                count += 1
            elapsed = time.perf_counter() - start
    finally:
        path.unlink()

    return {
        "test": "disk_random_read_4k",
        "file_size_mb": file_size_mb,
        "duration_sec": round(elapsed, 3),
        "iops": round(count / elapsed, 1),
    }


def _python_sort_throughput() -> dict[str, Any]:
    """Sort 1M random floats — proxy for in-memory query processing."""
    n = 1_000_000
    iterations = 5
    times = []
    for _ in range(iterations):
        arr = [random.random() for _ in range(n)]  # nosec B311
        start = time.perf_counter()
        arr.sort()
        times.append(time.perf_counter() - start)

    avg = statistics.mean(times)
    return {
        "test": "python_sort_1m_floats",
        "elements": n,
        "iterations": iterations,
        "avg_sec": round(avg, 4),
        "sorts_per_sec": round(1.0 / avg, 2),
    }


def _system_info() -> dict[str, Any]:
    """Collect system hardware information."""
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
    }

    # Total RAM
    proc_meminfo = Path("/proc/meminfo")
    if proc_meminfo.exists():
        for line in proc_meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                info["ram_gb"] = round(kb / 1024 / 1024, 1)
                break
    else:
        # macOS
        try:
            result = subprocess.run(  # nosec: B603, B607
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                check=True,
            )
            info["ram_gb"] = round(int(result.stdout.strip()) / 1024 / 1024 / 1024, 1)
        except Exception:
            info["ram_gb"] = None

    return info


def run_calibration() -> dict[str, Any]:
    """Run all calibration benchmarks and return results."""
    print("Collecting system info...")
    system = _system_info()
    print(f"  {system['cpu_count']} CPUs, {system.get('ram_gb', '?')} GB RAM, {system['platform']}")

    print("Running CPU single-thread benchmark (5s)...")
    cpu_st = _cpu_single_thread()
    print(f"  {cpu_st['ops_per_sec']:,.0f} SHA-256 ops/sec")

    print("Running CPU multi-thread benchmark (5s)...")
    cpu_mt = _cpu_multi_thread()
    print(f"  {cpu_mt['ops_per_sec']:,.0f} SHA-256 ops/sec across {cpu_mt['cores']} cores")

    print("Running memory bandwidth benchmark...")
    mem = _memory_bandwidth()
    print(f"  Write: {mem['write_mb_per_sec']:,.0f} MB/s, Read: {mem['read_mb_per_sec']:,.0f} MB/s")

    print("Running sequential write benchmark (256 MB)...")
    seq_w = _disk_sequential_write()
    print(f"  {seq_w['mb_per_sec']:,.0f} MB/s")

    print("Running sequential read benchmark (256 MB)...")
    seq_r = _disk_sequential_read()
    print(f"  {seq_r['mb_per_sec']:,.0f} MB/s")

    print("Running random read IOPS benchmark (5s)...")
    rand_r = _disk_random_iops()
    print(f"  {rand_r['iops']:,.0f} IOPS (4 KB random reads)")

    print("Running Python sort benchmark...")
    sort_b = _python_sort_throughput()
    print(f"  {sort_b['sorts_per_sec']:.1f} sorts/sec (1M floats)")

    return {
        "calibration_version": 1,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system": system,
        "benchmarks": {
            "cpu_single_thread": cpu_st,
            "cpu_multi_thread": cpu_mt,
            "memory_bandwidth": mem,
            "disk_sequential_write": seq_w,
            "disk_sequential_read": seq_r,
            "disk_random_read": rand_r,
            "python_sort": sort_b,
        },
    }


# ---------------------------------------------------------------------------
# Scaling logic
# ---------------------------------------------------------------------------

# Per-workload weight profiles: how much each hardware dimension affects latency.
# Weights sum to 1.0 for each workload.
WORKLOAD_WEIGHTS: dict[str, dict[str, float]] = {
    "point_read": {
        "cpu_st": 0.3,
        "cpu_mt": 0.0,
        "memory": 0.2,
        "seq_io": 0.0,
        "rand_io": 0.5,
    },
    "graph_traversal": {
        "cpu_st": 0.4,
        "cpu_mt": 0.0,
        "memory": 0.3,
        "seq_io": 0.0,
        "rand_io": 0.3,
    },
    "fulltext_search": {
        "cpu_st": 0.3,
        "cpu_mt": 0.0,
        "memory": 0.3,
        "seq_io": 0.0,
        "rand_io": 0.4,
    },
    "aggregation": {
        "cpu_st": 0.5,
        "cpu_mt": 0.0,
        "memory": 0.3,
        "seq_io": 0.0,
        "rand_io": 0.2,
    },
    "batch_write_nodes": {
        "cpu_st": 0.2,
        "cpu_mt": 0.1,
        "memory": 0.1,
        "seq_io": 0.3,
        "rand_io": 0.3,
    },
    "batch_write_full_tx": {
        "cpu_st": 0.2,
        "cpu_mt": 0.1,
        "memory": 0.1,
        "seq_io": 0.3,
        "rand_io": 0.3,
    },
    "concurrent_mixed": {
        "cpu_st": 0.1,
        "cpu_mt": 0.4,
        "memory": 0.2,
        "seq_io": 0.1,
        "rand_io": 0.2,
    },
}

DEFAULT_WEIGHTS: dict[str, float] = {
    "cpu_st": 0.3,
    "cpu_mt": 0.1,
    "memory": 0.2,
    "seq_io": 0.1,
    "rand_io": 0.3,
}


def compute_scaling_factors(baseline: dict[str, Any], local: dict[str, Any]) -> dict[str, float]:
    """Compute per-dimension scaling factors (local / baseline).

    A factor > 1.0 means local hardware is faster in that dimension.
    A factor < 1.0 means local hardware is slower.
    """
    bb = baseline["benchmarks"]
    lb = local["benchmarks"]

    factors: dict[str, float] = {}

    # CPU single-thread: higher ops/sec is better
    factors["cpu_st"] = lb["cpu_single_thread"]["ops_per_sec"] / bb["cpu_single_thread"]["ops_per_sec"]

    # CPU multi-thread: higher ops/sec is better
    factors["cpu_mt"] = lb["cpu_multi_thread"]["ops_per_sec"] / bb["cpu_multi_thread"]["ops_per_sec"]

    # Memory: average of read and write bandwidth; higher is better
    baseline_mem = (bb["memory_bandwidth"]["read_mb_per_sec"] + bb["memory_bandwidth"]["write_mb_per_sec"]) / 2
    local_mem = (lb["memory_bandwidth"]["read_mb_per_sec"] + lb["memory_bandwidth"]["write_mb_per_sec"]) / 2
    factors["memory"] = local_mem / baseline_mem

    # Sequential I/O: average of read and write; higher is better
    baseline_seq = (bb["disk_sequential_write"]["mb_per_sec"] + bb["disk_sequential_read"]["mb_per_sec"]) / 2
    local_seq = (lb["disk_sequential_write"]["mb_per_sec"] + lb["disk_sequential_read"]["mb_per_sec"]) / 2
    factors["seq_io"] = local_seq / baseline_seq

    # Random I/O: higher IOPS is better
    factors["rand_io"] = lb["disk_random_read"]["iops"] / bb["disk_random_read"]["iops"]

    return factors


def weighted_factor(factors: dict[str, float], weights: dict[str, float]) -> float:
    """Compute a single composite scaling factor from per-dimension factors and weights."""
    return sum(factors[dim] * weight for dim, weight in weights.items())


def scale_latency(value_ms: float, factor: float) -> float:
    """Scale a latency value. Higher factor = faster local = lower latency."""
    if factor <= 0:
        return value_ms
    return round(value_ms / factor, 3)


def scale_throughput(value_ops: float, factor: float) -> float:
    """Scale a throughput value. Higher factor = faster local = higher throughput."""
    return round(value_ops * factor, 1)


def identify_workload_type(workload_name: str) -> str:
    """Map a benchmark workload name to a weight profile key."""
    name = workload_name.lower().replace(" ", "_").replace("-", "_")

    for key in WORKLOAD_WEIGHTS:
        if key in name:
            return key

    # Heuristic matches
    if any(w in name for w in ["read", "lookup", "fetch", "get"]):
        return "point_read"
    if any(w in name for w in ["traverse", "expand", "hop", "explore", "center"]):
        return "graph_traversal"
    if any(w in name for w in ["search", "autocomplete", "fulltext"]):
        return "fulltext_search"
    if any(w in name for w in ["aggregate", "trend", "count", "stats", "gap"]):
        return "aggregation"
    if any(w in name for w in ["write", "insert", "merge", "batch", "load"]):
        return "batch_write_nodes"
    if any(w in name for w in ["concurrent", "mixed"]):
        return "concurrent_mixed"

    return "default"


def scale_benchmark_results(
    benchmark_results: dict[str, Any],
    factors: dict[str, float],
) -> dict[str, Any]:
    """Apply scaling factors to all workloads in a benchmark results file."""
    scaled: dict[str, Any] = {
        "original_backend": benchmark_results.get("backend", "unknown"),
        "original_host": benchmark_results.get("host", "unknown"),
        "original_instance": benchmark_results.get("instance_type", "unknown"),
        "scaling_factors": {k: round(v, 3) for k, v in factors.items()},
        "scaled_benchmarks": {},
    }

    benchmarks = benchmark_results.get("benchmarks", {})
    for workload_name, metrics in benchmarks.items():
        wtype = identify_workload_type(workload_name)
        weights = WORKLOAD_WEIGHTS.get(wtype, DEFAULT_WEIGHTS)
        composite = weighted_factor(factors, weights)

        scaled_metrics: dict[str, Any] = {"workload_type": wtype, "composite_factor": round(composite, 3)}

        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                if "ms" in key or "latency" in key or "duration" in key:
                    scaled_metrics[key] = scale_latency(value, composite)
                    scaled_metrics[f"{key}_original"] = value
                elif "ops" in key or "throughput" in key or "per_sec" in key:
                    scaled_metrics[key] = scale_throughput(value, composite)
                    scaled_metrics[f"{key}_original"] = value
                else:
                    scaled_metrics[key] = value
            else:
                scaled_metrics[key] = value

        scaled["scaled_benchmarks"][workload_name] = scaled_metrics

    # Scale insertion metrics if present
    if "insertion_metrics" in benchmark_results:
        composite_write = weighted_factor(factors, WORKLOAD_WEIGHTS["batch_write_nodes"])
        scaled_insertion: dict[str, Any] = {"composite_factor": round(composite_write, 3)}
        for key, value in benchmark_results["insertion_metrics"].items():
            if isinstance(value, dict):
                scaled_sub: dict[str, Any] = {}
                for k, v in value.items():
                    if isinstance(v, (int, float)):
                        if "sec" in k and "per" not in k:
                            scaled_sub[k] = scale_latency(v, composite_write)
                            scaled_sub[f"{k}_original"] = v
                        elif "per_sec" in k:
                            scaled_sub[k] = scale_throughput(v, composite_write)
                            scaled_sub[f"{k}_original"] = v
                        else:
                            scaled_sub[k] = v
                    else:
                        scaled_sub[k] = v
                scaled_insertion[key] = scaled_sub
            elif isinstance(value, (int, float)):
                if "sec" in key and "per" not in key:
                    scaled_insertion[key] = scale_latency(value, composite_write)
                    scaled_insertion[f"{key}_original"] = value
                else:
                    scaled_insertion[key] = value
            else:
                scaled_insertion[key] = value
        scaled["scaled_insertion_metrics"] = scaled_insertion

    return scaled


def print_scaling_summary(factors: dict[str, float], scaled: dict[str, Any]) -> None:
    """Print a human-readable summary of scaling results."""
    print()
    print("=" * 70)
    print("SCALING SUMMARY")
    print("=" * 70)
    print()
    print(f"Original environment: {scaled['original_instance']} ({scaled['original_host']})")
    print()

    print("Per-dimension scaling factors (local / baseline):")
    print(f"  {'Dimension':<20} {'Factor':>8}  {'Interpretation'}")
    print(f"  {'-' * 20} {'-' * 8}  {'-' * 30}")
    labels = {
        "cpu_st": "CPU (single)",
        "cpu_mt": "CPU (multi)",
        "memory": "Memory bandwidth",
        "seq_io": "Sequential I/O",
        "rand_io": "Random I/O",
    }
    for dim, factor in factors.items():
        label = labels.get(dim, dim)
        if factor > 1.05:
            interp = f"Local is {factor:.1f}x faster"
        elif factor < 0.95:
            interp = f"Local is {1 / factor:.1f}x slower"
        else:
            interp = "Roughly equivalent"
        print(f"  {label:<20} {factor:>8.3f}  {interp}")

    print()
    print("Scaled workload estimates:")
    print(f"  {'Workload':<35} {'Type':<20} {'Factor':>7}  {'p50 (orig)':>12} {'p50 (est)':>12}")
    print(f"  {'-' * 35} {'-' * 20} {'-' * 7}  {'-' * 12} {'-' * 12}")

    for name, metrics in scaled.get("scaled_benchmarks", {}).items():
        wtype = metrics.get("workload_type", "?")
        comp = metrics.get("composite_factor", 1.0)
        p50_orig = metrics.get("p50_ms_original")
        p50_scaled = metrics.get("p50_ms")

        orig_str = f"{p50_orig:.1f} ms" if p50_orig is not None else "—"
        scaled_str = f"{p50_scaled:.1f} ms" if p50_scaled is not None else "—"
        print(f"  {name:<35} {wtype:<20} {comp:>7.3f}  {orig_str:>12} {scaled_str:>12}")

    print()
    print("NOTE: These are estimates based on hardware calibration ratios.")
    print("Actual performance depends on database internals, caching, OS tuning,")
    print("dataset fit in RAM, and other factors not captured by micro-benchmarks.")
    print("Use these numbers for approximate order-of-magnitude comparisons only.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> None:
    """Run hardware calibration benchmarks."""
    print("=" * 60)
    print("Discogsography Benchmark Calibration")
    print("=" * 60)
    print()

    results = run_calibration()

    output_path = Path(args.output)
    output_path.write_text(json.dumps(results, indent=2))

    print()
    print(f"Results saved to {args.output}")
    print()
    print("Next steps:")
    print("  1. Run this same script on the Hetzner CX53 benchmark host")
    print("  2. Scale benchmark results to your environment:")
    print("     uv run python docs/investigations/calibration/calibrate.py scale \\")
    print("       --baseline hetzner-calibration.json \\")
    print(f"       --local {args.output} \\")
    print("       --benchmark-results docs/investigations/calibration/results/neo4j_large_*.json")


def cmd_scale(args: argparse.Namespace) -> None:
    """Scale benchmark results using calibration data."""
    baseline = json.loads(Path(args.baseline).read_text())
    local = json.loads(Path(args.local).read_text())
    bench = json.loads(Path(args.benchmark_results).read_text())

    if baseline.get("calibration_version") != local.get("calibration_version"):
        print("WARNING: Calibration versions differ. Results may not be comparable.", file=sys.stderr)

    factors = compute_scaling_factors(baseline, local)
    scaled = scale_benchmark_results(bench, factors)

    print_scaling_summary(factors, scaled)

    if args.output:
        Path(args.output).write_text(json.dumps(scaled, indent=2))
        print(f"\nScaled results saved to {args.output}")
    else:
        print("\nFull JSON (use --output to save to file):")
        print(json.dumps(scaled, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Hardware calibration and benchmark scaling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- run subcommand ---
    run_parser = subparsers.add_parser("run", help="Run hardware calibration benchmarks")
    run_parser.add_argument(
        "--output",
        "-o",
        default="calibration.json",
        help="Output file path (default: calibration.json)",
    )

    # --- scale subcommand ---
    scale_parser = subparsers.add_parser("scale", help="Scale benchmark results using calibration data")
    scale_parser.add_argument(
        "--baseline",
        required=True,
        help="Calibration JSON from the benchmark host (Hetzner CX53)",
    )
    scale_parser.add_argument(
        "--local",
        required=True,
        help="Calibration JSON from your local machine",
    )
    scale_parser.add_argument(
        "--benchmark-results",
        required=True,
        help="Benchmark results JSON to scale",
    )
    scale_parser.add_argument(
        "--output",
        "-o",
        help="Output file for scaled results (default: print to stdout)",
    )

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "scale":
        cmd_scale(args)


if __name__ == "__main__":
    main()
