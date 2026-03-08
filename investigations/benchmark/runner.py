"""Benchmark execution engine.

Generates synthetic data, inserts it into the target database via GraphBackend,
runs all workloads, and outputs results as JSON.

Usage:
    uv run python -m investigations.benchmark.runner \
      --backend neo4j \
      --uri bolt://localhost:7687 \
      --scale small \
      --output investigations/benchmark/results/neo4j_small.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import time
from typing import TYPE_CHECKING, Any

from investigations.benchmark.fixtures import generate_test_data
from investigations.benchmark.workloads import WORKLOADS, WorkloadType, get_workload_params


if TYPE_CHECKING:
    from investigations.backends.base import GraphBackend


def get_backend(name: str) -> GraphBackend:
    """Instantiate a GraphBackend by name."""
    if name == "neo4j":
        from investigations.backends.neo4j_backend import Neo4jBackend

        return Neo4jBackend()
    elif name == "memgraph":
        from investigations.backends.memgraph_backend import MemgraphBackend

        return MemgraphBackend()
    elif name == "age":
        from investigations.backends.age_backend import ApacheAGEBackend

        return ApacheAGEBackend()
    elif name == "falkordb":
        from investigations.backends.falkordb_backend import FalkorDBBackend

        return FalkorDBBackend()
    elif name == "arangodb":
        from investigations.backends.arangodb_backend import ArangoDBBackend

        return ArangoDBBackend()
    else:
        msg = f"Unknown backend: {name}. Choose from: neo4j, memgraph, age, falkordb, arangodb"
        raise ValueError(msg)


async def insert_data(backend: GraphBackend, data: dict[str, Any], batch_size: int = 500) -> dict[str, Any]:
    """Insert synthetic data into the database, returning insertion metrics."""
    metrics: dict[str, Any] = {}
    total_start = time.perf_counter()

    # Schema
    print("  Applying schema...")
    if hasattr(backend, "apply_schema"):
        await backend.apply_schema()
    for stmt in backend.get_schema_statements():
        try:
            await backend.execute_write(stmt)
        except Exception as e:
            print(f"    Schema warning: {e}")

    # Nodes: artists
    print(f"  Inserting {len(data['artists']):,} artists...")
    start = time.perf_counter()
    for i in range(0, len(data["artists"]), batch_size):
        batch = data["artists"][i : i + batch_size]
        rows = [{"id": a["id"], "name": a["name"], "sha256": a["sha256"]} for a in batch]
        query = backend.batch_merge_nodes_query("Artist", ["name", "sha256"])
        await backend.execute_write(query, {"rows": rows})
    elapsed = time.perf_counter() - start
    metrics["artists"] = {
        "count": len(data["artists"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["artists"]) / elapsed, 1),
    }

    # Nodes: labels
    print(f"  Inserting {len(data['labels']):,} labels...")
    start = time.perf_counter()
    for i in range(0, len(data["labels"]), batch_size):
        batch = data["labels"][i : i + batch_size]
        rows = [{"id": lbl["id"], "name": lbl["name"], "sha256": lbl["sha256"]} for lbl in batch]
        query = backend.batch_merge_nodes_query("Label", ["name", "sha256"])
        await backend.execute_write(query, {"rows": rows})
    elapsed = time.perf_counter() - start
    metrics["labels"] = {"count": len(data["labels"]), "duration_sec": round(elapsed, 2), "records_per_sec": round(len(data["labels"]) / elapsed, 1)}

    # Nodes: masters
    print(f"  Inserting {len(data['masters']):,} masters...")
    start = time.perf_counter()
    for i in range(0, len(data["masters"]), batch_size):
        batch = data["masters"][i : i + batch_size]
        rows = [{"id": m["id"], "name": m["title"], "sha256": m["sha256"]} for m in batch]
        query = backend.batch_merge_nodes_query("Master", ["name", "sha256"])
        await backend.execute_write(query, {"rows": rows})
    elapsed = time.perf_counter() - start
    metrics["masters"] = {
        "count": len(data["masters"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["masters"]) / elapsed, 1),
    }

    # Nodes: releases
    print(f"  Inserting {len(data['releases']):,} releases...")
    start = time.perf_counter()
    for i in range(0, len(data["releases"]), batch_size):
        batch = data["releases"][i : i + batch_size]
        rows = [{"id": r["id"], "name": r["title"], "sha256": r["sha256"]} for r in batch]
        query = backend.batch_merge_nodes_query("Release", ["name", "sha256"])
        await backend.execute_write(query, {"rows": rows})
    elapsed = time.perf_counter() - start
    metrics["releases"] = {
        "count": len(data["releases"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["releases"]) / elapsed, 1),
    }

    # Nodes: genres
    print(f"  Inserting {len(data['genres']):,} genres...")
    for g in data["genres"]:
        await backend.execute_write(
            backend.batch_merge_nodes_query("Genre", ["name"]),
            {"rows": [{"id": g["name"], "name": g["name"]}]},
        )

    # Nodes: styles
    print(f"  Inserting {len(data['styles']):,} styles...")
    for s in data["styles"]:
        await backend.execute_write(
            backend.batch_merge_nodes_query("Style", ["name"]),
            {"rows": [{"id": s["name"], "name": s["name"]}]},
        )

    # Relationships: BY
    print(f"  Inserting {len(data['by_rels']):,} BY relationships...")
    start = time.perf_counter()
    for i in range(0, len(data["by_rels"]), batch_size):
        batch = data["by_rels"][i : i + batch_size]
        query = backend.batch_create_relationships_query("Release", "BY", "Artist")
        await backend.execute_write(query, {"rows": batch})
    elapsed = time.perf_counter() - start
    metrics["by_rels"] = {
        "count": len(data["by_rels"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["by_rels"]) / max(elapsed, 0.001), 1),
    }

    # Relationships: ON
    print(f"  Inserting {len(data['on_rels']):,} ON relationships...")
    start = time.perf_counter()
    for i in range(0, len(data["on_rels"]), batch_size):
        batch = data["on_rels"][i : i + batch_size]
        query = backend.batch_create_relationships_query("Release", "ON", "Label")
        await backend.execute_write(query, {"rows": batch})
    elapsed = time.perf_counter() - start
    metrics["on_rels"] = {
        "count": len(data["on_rels"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["on_rels"]) / max(elapsed, 0.001), 1),
    }

    # Relationships: DERIVED_FROM
    print(f"  Inserting {len(data['derived_from_rels']):,} DERIVED_FROM relationships...")
    start = time.perf_counter()
    for i in range(0, len(data["derived_from_rels"]), batch_size):
        batch = data["derived_from_rels"][i : i + batch_size]
        query = backend.batch_create_relationships_query("Release", "DERIVED_FROM", "Master")
        await backend.execute_write(query, {"rows": batch})
    elapsed = time.perf_counter() - start
    metrics["derived_from_rels"] = {
        "count": len(data["derived_from_rels"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["derived_from_rels"]) / max(elapsed, 0.001), 1),
    }

    # Relationships: IS (genre/style) - uses name-based matching
    genre_rels = [r for r in data["is_rels"] if r["type"] == "genre"]
    style_rels = [r for r in data["is_rels"] if r["type"] == "style"]
    print(f"  Inserting {len(genre_rels):,} IS(genre) + {len(style_rels):,} IS(style) relationships...")
    start = time.perf_counter()
    for i in range(0, len(genre_rels), batch_size):
        batch = genre_rels[i : i + batch_size]
        rows = [{"from_id": r["from_id"], "to_id": r["to_id"]} for r in batch]
        query = backend.batch_create_relationships_query("Release", "IS", "Genre")
        await backend.execute_write(query, {"rows": rows})
    for i in range(0, len(style_rels), batch_size):
        batch = style_rels[i : i + batch_size]
        rows = [{"from_id": r["from_id"], "to_id": r["to_id"]} for r in batch]
        query = backend.batch_create_relationships_query("Release", "IS", "Style")
        await backend.execute_write(query, {"rows": rows})
    elapsed = time.perf_counter() - start
    metrics["is_rels"] = {
        "count": len(data["is_rels"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["is_rels"]) / max(elapsed, 0.001), 1),
    }

    # Relationships: MEMBER_OF
    print(f"  Inserting {len(data['member_of_rels']):,} MEMBER_OF relationships...")
    start = time.perf_counter()
    for i in range(0, len(data["member_of_rels"]), batch_size):
        batch = data["member_of_rels"][i : i + batch_size]
        query = backend.batch_create_relationships_query("Artist", "MEMBER_OF", "Artist")
        await backend.execute_write(query, {"rows": batch})
    elapsed = time.perf_counter() - start
    metrics["member_of_rels"] = {
        "count": len(data["member_of_rels"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["member_of_rels"]) / max(elapsed, 0.001), 1),
    }

    # Relationships: ALIAS_OF
    print(f"  Inserting {len(data['alias_of_rels']):,} ALIAS_OF relationships...")
    start = time.perf_counter()
    for i in range(0, len(data["alias_of_rels"]), batch_size):
        batch = data["alias_of_rels"][i : i + batch_size]
        query = backend.batch_create_relationships_query("Artist", "ALIAS_OF", "Artist")
        await backend.execute_write(query, {"rows": batch})
    elapsed = time.perf_counter() - start
    metrics["alias_of_rels"] = {
        "count": len(data["alias_of_rels"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["alias_of_rels"]) / max(elapsed, 0.001), 1),
    }

    # Relationships: SUBLABEL_OF
    print(f"  Inserting {len(data['sublabel_of_rels']):,} SUBLABEL_OF relationships...")
    start = time.perf_counter()
    for i in range(0, len(data["sublabel_of_rels"]), batch_size):
        batch = data["sublabel_of_rels"][i : i + batch_size]
        query = backend.batch_create_relationships_query("Label", "SUBLABEL_OF", "Label")
        await backend.execute_write(query, {"rows": batch})
    elapsed = time.perf_counter() - start
    metrics["sublabel_of_rels"] = {
        "count": len(data["sublabel_of_rels"]),
        "duration_sec": round(elapsed, 2),
        "records_per_sec": round(len(data["sublabel_of_rels"]) / max(elapsed, 0.001), 1),
    }

    # Relationships: PART_OF
    print(f"  Inserting {len(data['part_of_rels']):,} PART_OF relationships...")
    for i in range(0, len(data["part_of_rels"]), batch_size):
        batch = data["part_of_rels"][i : i + batch_size]
        rows = [{"from_id": r["from_id"], "to_id": r["to_id"]} for r in batch]
        query = backend.batch_create_relationships_query("Style", "PART_OF", "Genre")
        await backend.execute_write(query, {"rows": rows})

    total_elapsed = time.perf_counter() - total_start
    metrics["total_duration_sec"] = round(total_elapsed, 2)
    print(f"  Insertion complete in {total_elapsed:.1f}s")

    return metrics


async def run_workload(
    backend: GraphBackend,
    workload_name: str,
    data: dict[str, Any],
    iterations: int,
    warmup: int = 5,
) -> dict[str, Any]:
    """Execute a single workload and collect latency metrics."""
    # Warmup
    for _ in range(min(warmup, iterations)):
        params = get_workload_params(workload_name, data)
        await _execute_single(backend, workload_name, params, data)

    # Measured iterations
    latencies: list[float] = []
    errors = 0
    for _ in range(iterations):
        params = get_workload_params(workload_name, data)
        start = time.perf_counter_ns()
        try:
            await _execute_single(backend, workload_name, params, data)
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    Warning: {workload_name} error: {e}")
            continue
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        latencies.append(elapsed_ms)

    if not latencies:
        return {"workload": workload_name, "error": f"All {iterations} iterations failed"}

    sorted_lat = sorted(latencies)
    return {
        "workload": workload_name,
        "iterations": len(latencies),
        "errors": errors,
        "p50_ms": round(statistics.median(sorted_lat), 3),
        "p95_ms": round(sorted_lat[int(0.95 * len(sorted_lat))], 3),
        "p99_ms": round(sorted_lat[int(0.99 * len(sorted_lat))], 3),
        "mean_ms": round(statistics.mean(sorted_lat), 3),
        "min_ms": round(min(sorted_lat), 3),
        "max_ms": round(max(sorted_lat), 3),
        "throughput_ops_sec": round(1000.0 / statistics.mean(sorted_lat), 1) if statistics.mean(sorted_lat) > 0 else 0,
    }


async def _execute_single(
    backend: GraphBackend,
    workload_name: str,
    params: dict[str, Any],
    data: dict[str, Any],  # noqa: ARG001
) -> None:
    """Execute a single iteration of a workload."""
    if workload_name == "point_read":
        query = backend.point_lookup_query("Artist")
        await backend.execute_read(query, {"id": params["id"]})

    elif workload_name == "graph_traversal":
        query = backend.traversal_query()
        await backend.execute_read(query, params)

    elif workload_name == "fulltext_search":
        query = backend.fulltext_search_query("artist_fulltext", "search_term")
        await backend.execute_read(query, {"search_term": params["search_term"]})

    elif workload_name == "aggregation":
        query = backend.aggregation_query()
        await backend.execute_read(query, {"name": params["name"]})

    elif workload_name == "batch_write_nodes":
        query = backend.batch_merge_nodes_query("Artist", ["name", "sha256"])
        await backend.execute_write(query, {"rows": params["rows"]})

    elif workload_name == "batch_write_full_tx":
        release = params["release"]
        queries: list[tuple[str, dict[str, Any]]] = [
            (
                backend.batch_merge_nodes_query("Release", ["name", "sha256"]),
                {"rows": [{"id": release["id"], "name": release["title"], "sha256": release["sha256"]}]},
            ),
        ]
        await backend.execute_write_batch(queries)


async def run_concurrent_mixed(
    backend: GraphBackend,
    data: dict[str, Any],
    readers: int = 4,
    writers: int = 2,
    duration_seconds: int = 30,
) -> dict[str, Any]:
    """Run concurrent read/write workload."""
    read_latencies: list[float] = []
    write_latencies: list[float] = []
    read_errors = 0
    write_errors = 0

    deadline = time.perf_counter() + duration_seconds

    async def reader_task() -> None:
        nonlocal read_errors
        while time.perf_counter() < deadline:
            params = get_workload_params("point_read", data)
            start = time.perf_counter_ns()
            try:
                query = backend.point_lookup_query("Artist")
                await backend.execute_read(query, {"id": params["id"]})
                elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
                read_latencies.append(elapsed_ms)
            except Exception:
                read_errors += 1

    async def writer_task() -> None:
        nonlocal write_errors
        while time.perf_counter() < deadline:
            params = get_workload_params("batch_write_nodes", data)
            start = time.perf_counter_ns()
            try:
                query = backend.batch_merge_nodes_query("Artist", ["name", "sha256"])
                await backend.execute_write(query, {"rows": params["rows"][:10]})
                elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
                write_latencies.append(elapsed_ms)
            except Exception:
                write_errors += 1

    tasks = [asyncio.create_task(reader_task()) for _ in range(readers)]
    tasks.extend(asyncio.create_task(writer_task()) for _ in range(writers))
    await asyncio.gather(*tasks)

    result: dict[str, Any] = {
        "workload": "concurrent_mixed",
        "duration_seconds": duration_seconds,
        "readers": readers,
        "writers": writers,
    }

    if read_latencies:
        sorted_reads = sorted(read_latencies)
        result["read_ops"] = len(read_latencies)
        result["read_errors"] = read_errors
        result["read_p50_ms"] = round(statistics.median(sorted_reads), 3)
        result["read_p95_ms"] = round(sorted_reads[int(0.95 * len(sorted_reads))], 3)
        result["read_throughput_ops_sec"] = round(len(read_latencies) / duration_seconds, 1)

    if write_latencies:
        sorted_writes = sorted(write_latencies)
        result["write_ops"] = len(write_latencies)
        result["write_errors"] = write_errors
        result["write_p50_ms"] = round(statistics.median(sorted_writes), 3)
        result["write_p95_ms"] = round(sorted_writes[int(0.95 * len(sorted_writes))], 3)
        result["write_throughput_ops_sec"] = round(len(write_latencies) / duration_seconds, 1)

    return result


async def run_all_benchmarks(
    backend: GraphBackend,
    data: dict[str, Any],
    skip_load: bool = False,
) -> dict[str, Any]:
    """Run the complete benchmark suite."""
    results: dict[str, Any] = {
        "backend": backend.name,
        "scale": data["scale"],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if not skip_load:
        print("\n=== Data Insertion ===")
        results["insertion_metrics"] = await insert_data(backend, data)

    print("\n=== Running Benchmarks ===")
    benchmarks: dict[str, Any] = {}

    for workload in WORKLOADS:
        if workload.workload_type == WorkloadType.MIXED:
            print(f"  Running {workload.name} ({workload.duration_seconds}s)...")
            benchmarks[workload.name] = await run_concurrent_mixed(
                backend,
                data,
                readers=workload.readers,
                writers=workload.writers,
                duration_seconds=workload.duration_seconds,
            )
        else:
            print(f"  Running {workload.name} ({workload.iterations} iterations)...")
            benchmarks[workload.name] = await run_workload(
                backend,
                workload.name,
                data,
                workload.iterations,
            )

        # Print summary
        bm = benchmarks[workload.name]
        if "p50_ms" in bm:
            print(f"    p50={bm['p50_ms']:.1f}ms  p95={bm['p95_ms']:.1f}ms  throughput={bm.get('throughput_ops_sec', 'N/A')} ops/s")
        elif "read_p50_ms" in bm:
            print(f"    reads: p50={bm['read_p50_ms']:.1f}ms  writes: p50={bm.get('write_p50_ms', 'N/A')}ms")

    results["benchmarks"] = benchmarks
    return results


async def main_async(args: argparse.Namespace) -> None:
    """Main async entry point."""
    backend = get_backend(args.backend)
    auth = (args.user, args.password) if args.user else None

    print(f"=== Benchmark: {args.backend} at scale={args.scale} ===")
    print(f"  URI: {args.uri}")

    await backend.connect(args.uri, auth=auth)

    try:
        if not await backend.health_check():
            print("ERROR: Database health check failed. Is it running?", file=sys.stderr)
            sys.exit(1)
        print("  Health check: OK")

        if args.clear:
            print("  Clearing existing data...")
            await backend.clear_all_data()

        data = generate_test_data(scale=args.scale, seed=args.seed)

        if args.load_only:
            await insert_data(backend, data)
            print("\nData loaded. Skipping benchmarks (--load-only).")
            return

        results = run_all_benchmarks(backend, data, skip_load=args.skip_load)
        results_json = await results

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results_json, indent=2))
        print(f"\n=== Results saved to {args.output} ===")

    finally:
        await backend.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Graph database benchmark runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark Neo4j locally
  uv run python -m investigations.benchmark.runner \\
    --backend neo4j --uri bolt://localhost:7687 --scale small

  # Benchmark Memgraph
  uv run python -m investigations.benchmark.runner \\
    --backend memgraph --uri bolt://localhost:7688 --scale small

  # Load data only (no benchmarks)
  uv run python -m investigations.benchmark.runner \\
    --backend neo4j --uri bolt://localhost:7687 --load-only
        """,
    )
    parser.add_argument("--backend", required=True, choices=["neo4j", "memgraph", "age", "falkordb", "arangodb"])
    parser.add_argument("--uri", required=True, help="Database connection URI")
    parser.add_argument("--user", default=None, help="Database username")
    parser.add_argument("--password", default=None, help="Database password")
    parser.add_argument("--scale", default="small", choices=["small", "large"])
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument(
        "--output", "-o", default=None, help="Output JSON path (default: investigations/benchmark/results/<backend>_<scale>_<timestamp>.json)"
    )
    parser.add_argument("--load-only", action="store_true", help="Only load data, skip benchmarks")
    parser.add_argument("--skip-load", action="store_true", help="Skip data loading, run benchmarks only")
    parser.add_argument("--clear", action="store_true", help="Clear existing data before loading")

    args = parser.parse_args()

    if args.output is None:
        ts = time.strftime("%Y-%m-%d_%H%M%S")
        args.output = f"investigations/benchmark/results/{args.backend}_{args.scale}_{ts}.json"

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
