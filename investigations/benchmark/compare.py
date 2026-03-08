"""Side-by-side comparison of benchmark results.

Usage:
    uv run python -m investigations.benchmark.compare \
      investigations/benchmark/results/neo4j_small_*.json \
      investigations/benchmark/results/memgraph_small_*.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def load_results(path: str) -> dict[str, Any]:
    """Load benchmark results from a JSON file."""
    result: dict[str, Any] = json.loads(Path(path).read_text())
    return result


def format_ms(value: float | None) -> str:
    if value is None:
        return "—"
    if value < 1:
        return f"{value:.2f}ms"
    if value < 100:
        return f"{value:.1f}ms"
    return f"{value:.0f}ms"


def format_ops(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return f"{value:.0f}"


def delta_pct(baseline: float, candidate: float) -> str:
    """Calculate percentage change from baseline to candidate."""
    if baseline == 0:
        return "—"
    pct = ((candidate - baseline) / baseline) * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def compare_two(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    """Print side-by-side comparison of two benchmark results."""
    b_name = baseline.get("backend", "baseline")
    c_name = candidate.get("backend", "candidate")

    print()
    print("=" * 85)
    print(f"  BENCHMARK COMPARISON: {b_name} vs {c_name}")
    print(f"  Scale: {baseline.get('scale', '?')} | {candidate.get('scale', '?')}")
    print("=" * 85)

    # Insertion metrics
    b_ins = baseline.get("insertion_metrics", {})
    c_ins = candidate.get("insertion_metrics", {})
    if b_ins and c_ins:
        print()
        print("  INSERTION METRICS")
        print(f"  {'Entity':<20} {'':>3} {b_name:>12} {c_name:>12} {'Delta':>10}")
        print(f"  {'-' * 20} {'':>3} {'-' * 12} {'-' * 12} {'-' * 10}")

        for key in ["artists", "labels", "masters", "releases"]:
            b_val = b_ins.get(key, {}).get("records_per_sec")
            c_val = c_ins.get(key, {}).get("records_per_sec")
            if b_val is not None and c_val is not None:
                delta = delta_pct(b_val, c_val)
                print(f"  {key:<20} {'r/s':>3} {format_ops(b_val):>12} {format_ops(c_val):>12} {delta:>10}")

        b_total = b_ins.get("total_duration_sec")
        c_total = c_ins.get("total_duration_sec")
        if b_total is not None and c_total is not None:
            delta = delta_pct(b_total, c_total)
            print(f"  {'total_duration':<20} {'sec':>3} {b_total:>12.1f} {c_total:>12.1f} {delta:>10}")

    # Query benchmarks
    b_bench = baseline.get("benchmarks", {})
    c_bench = candidate.get("benchmarks", {})

    if b_bench and c_bench:
        print()
        print("  QUERY BENCHMARKS (latency)")
        print(f"  {'Workload':<25} {'Metric':>6} {b_name:>12} {c_name:>12} {'Delta':>10}")
        print(f"  {'-' * 25} {'-' * 6} {'-' * 12} {'-' * 12} {'-' * 10}")

        all_workloads = sorted(set(list(b_bench.keys()) + list(c_bench.keys())))
        for wl in all_workloads:
            b_wl = b_bench.get(wl, {})
            c_wl = c_bench.get(wl, {})

            # Standard workloads
            for metric in ["p50_ms", "p95_ms", "p99_ms"]:
                b_val = b_wl.get(metric)
                c_val = c_wl.get(metric)
                if b_val is not None or c_val is not None:
                    delta = delta_pct(b_val, c_val) if b_val and c_val else "—"
                    label = metric.replace("_ms", "")
                    print(f"  {wl:<25} {label:>6} {format_ms(b_val):>12} {format_ms(c_val):>12} {delta:>10}")

            # Concurrent workloads
            for prefix in ["read_", "write_"]:
                b_p50 = b_wl.get(f"{prefix}p50_ms")
                c_p50 = c_wl.get(f"{prefix}p50_ms")
                if b_p50 is not None or c_p50 is not None:
                    delta = delta_pct(b_p50, c_p50) if b_p50 and c_p50 else "—"
                    print(f"  {wl:<25} {prefix + 'p50':>6} {format_ms(b_p50):>12} {format_ms(c_p50):>12} {delta:>10}")

        # Throughput
        print()
        print("  QUERY BENCHMARKS (throughput)")
        print(f"  {'Workload':<25} {'Metric':>8} {b_name:>12} {c_name:>12} {'Delta':>10}")
        print(f"  {'-' * 25} {'-' * 8} {'-' * 12} {'-' * 12} {'-' * 10}")

        for wl in all_workloads:
            b_wl = b_bench.get(wl, {})
            c_wl = c_bench.get(wl, {})

            for metric in ["throughput_ops_sec", "read_throughput_ops_sec", "write_throughput_ops_sec"]:
                b_val = b_wl.get(metric)
                c_val = c_wl.get(metric)
                if b_val is not None or c_val is not None:
                    delta = delta_pct(b_val, c_val) if b_val and c_val else "—"
                    label = metric.replace("_ops_sec", "").replace("throughput", "ops/s")
                    print(f"  {wl:<25} {label:>8} {format_ops(b_val):>12} {format_ops(c_val):>12} {delta:>10}")

    print()
    print("  NOTE: Negative delta = candidate is faster (lower latency / shorter duration)")
    print("        Positive delta = candidate is faster (higher throughput)")
    print()


def compare_many(files: list[str]) -> None:
    """Compare multiple result files. First file is treated as baseline."""
    results = [load_results(f) for f in files]

    if len(results) < 2:
        print("Need at least 2 result files to compare.", file=sys.stderr)
        sys.exit(1)

    baseline = results[0]
    for candidate in results[1:]:
        compare_two(baseline, candidate)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare benchmark results")
    parser.add_argument("files", nargs="+", help="Benchmark result JSON files (first = baseline)")
    parser.add_argument("--output", "-o", help="Save comparison as markdown")

    args = parser.parse_args()
    compare_many(args.files)


if __name__ == "__main__":
    main()
