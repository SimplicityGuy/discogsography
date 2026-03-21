#!/usr/bin/env python3
"""Discogsography API Performance Test Runner.

Sequentially times all API query endpoints, computes statistics,
and writes results to JSON and human-readable report files.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from itertools import combinations
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

import httpx
import yaml


# ---------------------------------------------------------------------------
# Database index listing
# ---------------------------------------------------------------------------


def list_neo4j_indexes(config: dict[str, Any]) -> list[str]:
    """List all Neo4j indexes. Returns formatted lines for the report."""
    uri = config.get("neo4j_uri")
    if not uri:
        return ["  (neo4j_uri not configured — skipped)"]
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            uri,
            auth=(config.get("neo4j_user", "neo4j"), config.get("neo4j_password", "")),
        )
        with driver.session() as session:
            result = session.run("SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state")
            lines = []
            lines.append(f"  {'Name':<40} {'Type':<12} {'Entity':<8} {'Labels/Types':<25} {'Properties':<30} {'State':<8}")
            lines.append(f"  {'-' * 123}")
            for record in result:
                labels = ", ".join(record["labelsOrTypes"] or [])
                props = ", ".join(record["properties"] or [])
                lines.append(f"  {record['name']:<40} {record['type']:<12} {record['entityType']:<8} {labels:<25} {props:<30} {record['state']:<8}")
        driver.close()
        return lines if len(lines) > 2 else ["  (no indexes found)"]
    except Exception as exc:
        return [f"  (failed to connect: {exc})"]


def list_postgres_indexes(config: dict[str, Any]) -> list[str]:
    """List all PostgreSQL indexes. Returns formatted lines for the report."""
    url = config.get("postgres_url")
    if not url:
        return ["  (postgres_url not configured — skipped)"]
    try:
        import psycopg2

        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute("""
            SELECT schemaname, tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname
        """)
        lines = []
        lines.append(f"  {'Table':<30} {'Index Name':<40} {'Definition'}")
        lines.append(f"  {'-' * 120}")
        for row in cur.fetchall():
            lines.append(f"  {row[1]:<30} {row[2]:<40} {row[3]}")
        cur.close()
        conn.close()
        return lines if len(lines) > 2 else ["  (no indexes found)"]
    except Exception as exc:
        return [f"  (failed to connect: {exc})"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_config(path: str) -> dict[str, Any]:
    """Load and return YAML config."""
    with Path(path).open() as f:
        return yaml.safe_load(f)


def wait_for_health(url: str, retries: int, interval: int, timeout: int) -> bool:
    """Wait for the API health endpoint to respond 200."""
    print(f"Waiting for API health at {url} ...")
    for attempt in range(1, retries + 1):
        try:
            resp = httpx.get(url, timeout=timeout)
            if resp.status_code == 200:
                print(f"  API healthy (attempt {attempt}/{retries})")
                return True
        except httpx.ConnectError:
            pass
        except httpx.TimeoutException:
            pass
        print(f"  Attempt {attempt}/{retries} — not ready, retrying in {interval}s")
        time.sleep(interval)
    return False


def percentile(values: list[float], pct: float) -> float:
    """Compute the given percentile from a sorted list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (pct / 100.0) * (len(sorted_vals) - 1)
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return sorted_vals[lower]
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def compute_stats(timings: list[float]) -> dict[str, float]:
    """Compute min/avg/max/p95 from a list of elapsed times."""
    if not timings:
        return {"min": 0.0, "avg": 0.0, "max": 0.0, "p95": 0.0}
    return {
        "min": round(min(timings), 4),
        "avg": round(sum(timings) / len(timings), 4),
        "max": round(max(timings), 4),
        "p95": round(percentile(timings, 95), 4),
    }


# ---------------------------------------------------------------------------
# Request runner
# ---------------------------------------------------------------------------


def timed_get(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """Make a GET request and return timing + response metadata."""
    start = time.perf_counter()
    try:
        resp = client.get(url, params=params)
        elapsed = time.perf_counter() - start
        return {
            "status": resp.status_code,
            "elapsed": round(elapsed, 4),
            "size": len(resp.content),
            "error": None,
        }
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return {
            "status": 0,
            "elapsed": round(elapsed, 4),
            "size": 0,
            "error": str(exc),
        }


def run_endpoint(
    client: httpx.Client,
    name: str,
    url: str,
    params: dict[str, str] | None,
    iterations: int,
    *,
    max_429_retries: int = 4,
    base_429_delay: float = 32.0,
    max_429_delay: float = 300.0,
) -> dict[str, Any]:
    """Run an endpoint N times, collect results and stats.

    If a 429 (Too Many Requests) response is received, pauses with
    exponential backoff (32s, 64s, 128s, 256s) and retries that
    iteration, capping at 5 minutes per pause.
    """
    runs = []
    for i in range(iterations):
        retries = 0
        while True:
            result = timed_get(client, url, params)
            if result["status"] == 429 and retries < max_429_retries:
                retries += 1
                delay = min(base_429_delay * (2 ** (retries - 1)), max_429_delay)
                print(f"  [{i + 1}/{iterations}] {name} -> 429 rate limited, pausing {delay:.0f}s (retry {retries}/{max_429_retries})")
                time.sleep(delay)
                continue
            break
        runs.append(result)
        status_indicator = f"{result['status']}" if result["status"] else f"ERR: {result['error']}"
        retry_note = f" (after {retries} 429 retries)" if retries > 0 else ""
        print(f"  [{i + 1}/{iterations}] {name} -> {status_indicator} in {result['elapsed']:.4f}s{retry_note}")

    timings = [r["elapsed"] for r in runs if r["error"] is None and r["status"] != 429]
    errors = sum(1 for r in runs if r["error"] is not None or r["status"] >= 400)

    return {
        "endpoint": name,
        "url": url,
        "params": params,
        "iterations": iterations,
        "errors": errors,
        "stats": compute_stats(timings),
        "runs": runs,
    }


# ---------------------------------------------------------------------------
# ID resolution
# ---------------------------------------------------------------------------


def resolve_ids(
    client: httpx.Client,
    base_url: str,
    entities: list[str],
    entity_type: str,
    *,
    max_429_retries: int = 4,
    base_429_delay: float = 32.0,
    max_429_delay: float = 300.0,
) -> dict[str, int | None]:
    """Resolve entity names to node IDs via autocomplete."""
    ids: dict[str, int | None] = {}
    for name in entities:
        retries = 0
        while True:
            resp = client.get(
                f"{base_url}/api/autocomplete",
                params={"q": name, "type": entity_type, "limit": "1"},
            )
            if resp.status_code == 429 and retries < max_429_retries:
                retries += 1
                delay = min(base_429_delay * (2 ** (retries - 1)), max_429_delay)
                print(f"  {entity_type} '{name}' -> 429 rate limited, pausing {delay:.0f}s (retry {retries}/{max_429_retries})")
                time.sleep(delay)
                continue
            break
        if resp.status_code == 200:
            data = resp.json()
            results = data if isinstance(data, list) else data.get("results", [])
            if results:
                ids[name] = results[0].get("id")
            else:
                print(f"  WARNING: No autocomplete result for {entity_type} '{name}'")
                ids[name] = None
        else:
            print(f"  WARNING: Autocomplete failed for {entity_type} '{name}' (HTTP {resp.status_code})")
            ids[name] = None
    return ids


# ---------------------------------------------------------------------------
# Test definitions
# ---------------------------------------------------------------------------


def build_test_plan(
    config: dict[str, Any],
    artist_ids: dict[str, int | None],
    label_ids: dict[str, int | None],
) -> list[dict[str, Any]]:
    """Build the full list of endpoint tests to run."""
    base = config["api_base_url"]
    tests: list[dict[str, Any]] = []

    # --- Static endpoints (no parameters, do DB queries) ---
    static_endpoints: list[tuple[str, str, dict[str, str] | None]] = [
        ("explore/year-range", f"{base}/api/explore/year-range", None),
        ("explore/genre-emergence", f"{base}/api/explore/genre-emergence", {"before_year": "2025"}),
        ("genre-tree", f"{base}/api/genre-tree", None),
        ("insights/top-artists", f"{base}/api/insights/top-artists", None),
        ("insights/label-longevity", f"{base}/api/insights/label-longevity", None),
        ("insights/this-month", f"{base}/api/insights/this-month", None),
        ("insights/data-completeness", f"{base}/api/insights/data-completeness", None),
        ("insights/status", f"{base}/api/insights/status", None),
    ]
    for name, url, params in static_endpoints:
        tests.append({"name": name, "url": url, "params": params})

    # --- Insights genre trends (per genre) ---
    for genre_name in config.get("genres", []):
        tests.append(
            {
                "name": f"insights/genre-trends/{genre_name}",
                "url": f"{base}/api/insights/genre-trends",
                "params": {"genre": genre_name},
            }
        )

    # --- Autocomplete (per entity type + name) ---
    for entity_type, entities in [
        ("artist", config.get("artists", [])),
        ("genre", config.get("genres", [])),
        ("style", config.get("styles", [])),
        ("label", config.get("labels", [])),
    ]:
        for entity_name in entities:
            tests.append(
                {
                    "name": f"autocomplete/{entity_type}/{entity_name}",
                    "url": f"{base}/api/autocomplete",
                    "params": {"q": entity_name, "type": entity_type, "limit": "10"},
                }
            )

    # --- Explore (per entity type + name) ---
    for entity_type, entities in [
        ("artist", config.get("artists", [])),
        ("genre", config.get("genres", [])),
        ("style", config.get("styles", [])),
        ("label", config.get("labels", [])),
    ]:
        for entity_name in entities:
            tests.append(
                {
                    "name": f"explore/{entity_type}/{entity_name}",
                    "url": f"{base}/api/explore",
                    "params": {"name": entity_name, "type": entity_type},
                }
            )

    # --- Trends (per entity type + name) ---
    for entity_type, entities in [
        ("artist", config.get("artists", [])),
        ("genre", config.get("genres", [])),
        ("style", config.get("styles", [])),
        ("label", config.get("labels", [])),
    ]:
        for entity_name in entities:
            tests.append(
                {
                    "name": f"trends/{entity_type}/{entity_name}",
                    "url": f"{base}/api/trends",
                    "params": {"name": entity_name, "type": entity_type},
                }
            )

    # --- Search (per entity name, all types) ---
    all_entities = config.get("artists", []) + config.get("genres", []) + config.get("styles", []) + config.get("labels", [])
    for entity_name in all_entities:
        tests.append(
            {
                "name": f"search/{entity_name}",
                "url": f"{base}/api/search",
                "params": {"q": entity_name},
            }
        )

    # --- Path (all artist pair combinations) ---
    artists = config.get("artists", [])
    for from_artist, to_artist in combinations(artists, 2):
        tests.append(
            {
                "name": f"path/{from_artist} -> {to_artist}",
                "url": f"{base}/api/path",
                "params": {
                    "from_name": from_artist,
                    "from_type": "artist",
                    "to_name": to_artist,
                    "to_type": "artist",
                },
            }
        )

    # --- Label DNA (requires resolved IDs) ---
    for label_name, label_id in label_ids.items():
        if label_id is None:
            continue
        tests.append(
            {
                "name": f"label-dna/{label_name}",
                "url": f"{base}/api/label/{label_id}/dna",
                "params": None,
            }
        )
        tests.append(
            {
                "name": f"label-similar/{label_name}",
                "url": f"{base}/api/label/{label_id}/similar",
                "params": {"limit": "5"},
            }
        )

    # --- Label DNA Compare (all labels with resolved IDs) ---
    resolved_label_ids = [str(lid) for lid in label_ids.values() if lid is not None]
    if len(resolved_label_ids) >= 2:
        tests.append(
            {
                "name": "label-dna-compare",
                "url": f"{base}/api/label/dna/compare",
                "params": {"ids": ",".join(resolved_label_ids)},
            }
        )

    # --- Artist Similarity (requires resolved IDs) ---
    for artist_name, artist_id in artist_ids.items():
        if artist_id is None:
            continue
        tests.append(
            {
                "name": f"artist-similar/{artist_name}",
                "url": f"{base}/api/recommend/similar/artist/{artist_id}",
                "params": {"limit": "5"},
            }
        )

    # --- Collaborators (requires resolved IDs) ---
    for artist_name, artist_id in artist_ids.items():
        if artist_id is None:
            continue
        tests.append(
            {
                "name": f"collaborators/{artist_name}",
                "url": f"{base}/api/collaborators/{artist_id}",
                "params": {"limit": "20"},
            }
        )

    # --- Node Details (requires resolved IDs) ---
    for artist_name, artist_id in artist_ids.items():
        if artist_id is None:
            continue
        tests.append(
            {
                "name": f"node-details/artist/{artist_name}",
                "url": f"{base}/api/node/{artist_id}",
                "params": {"type": "artist"},
            }
        )
    for label_name, label_id in label_ids.items():
        if label_id is None:
            continue
        tests.append(
            {
                "name": f"node-details/label/{label_name}",
                "url": f"{base}/api/node/{label_id}",
                "params": {"type": "label"},
            }
        )

    # --- Expand (requires resolved IDs, tests releases category) ---
    for artist_name, artist_id in artist_ids.items():
        if artist_id is None:
            continue
        tests.append(
            {
                "name": f"expand/artist/{artist_name}/releases",
                "url": f"{base}/api/expand",
                "params": {
                    "node_id": str(artist_id),
                    "type": "artist",
                    "category": "releases",
                    "limit": "20",
                },
            }
        )
    for label_name, label_id in label_ids.items():
        if label_id is None:
            continue
        tests.append(
            {
                "name": f"expand/label/{label_name}/releases",
                "url": f"{base}/api/expand",
                "params": {
                    "node_id": str(label_id),
                    "type": "label",
                    "category": "releases",
                    "limit": "20",
                },
            }
        )

    return tests


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _verify_output_dir(output_dir: Path) -> None:
    """Verify the output directory exists and is writable.

    Creates the directory if needed. Exits with a clear message if the
    directory cannot be written to (e.g. Docker volume permission issues).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    test_file = output_dir / ".write-test"
    try:
        test_file.write_text("ok")
        test_file.unlink()
    except OSError as exc:
        print(f"ERROR: Output directory '{output_dir}' is not writable: {exc}")
        print("  Hint: ensure the Docker volume mount has correct permissions.")
        sys.exit(1)


def write_report(
    results: list[dict[str, Any]],
    output_dir: Path,
    *,
    neo4j_indexes: list[str] | None = None,
    postgres_indexes: list[str] | None = None,
) -> None:
    """Write JSON results and human-readable report."""
    _verify_output_dir(output_dir)

    # JSON output
    json_path = output_dir / "perftest-results.json"
    report_data = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "total_endpoints": len(results),
        "results": results,
    }
    with json_path.open("w") as f:
        json.dump(report_data, f, indent=2)
    print(f"\nJSON results written to {json_path}")

    # Human-readable report
    report_path = output_dir / "perftest-report.txt"
    lines = [
        "=" * 78,
        "  Discogsography API Performance Test Report",
        f"  Generated: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 78,
        "",
    ]

    # Database indexes section
    if neo4j_indexes or postgres_indexes:
        lines.append("--- NEO4J INDEXES ---")
        lines.extend(neo4j_indexes or ["  (not collected)"])
        lines.append("")
        lines.append("--- POSTGRESQL INDEXES ---")
        lines.extend(postgres_indexes or ["  (not collected)"])
        lines.append("")

    # Group results by category
    categories: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        cat = r["endpoint"].split("/")[0]
        categories.setdefault(cat, []).append(r)

    for cat, cat_results in categories.items():
        lines.append(f"--- {cat.upper()} ---")
        lines.append(f"  {'Endpoint':<50} {'Min':>8} {'Avg':>8} {'Max':>8} {'P95':>8} {'Err':>4}")
        lines.append(f"  {'-' * 86}")
        for r in cat_results:
            s = r["stats"]
            lines.append(f"  {r['endpoint']:<50} {s['min']:>7.4f}s {s['avg']:>7.4f}s {s['max']:>7.4f}s {s['p95']:>7.4f}s {r['errors']:>4}")
        lines.append("")

    # Summary
    all_avgs = [r["stats"]["avg"] for r in results if r["stats"]["avg"] > 0]
    total_errors = sum(r["errors"] for r in results)
    lines.append("--- SUMMARY ---")
    lines.append(f"  Total endpoints tested: {len(results)}")
    lines.append(f"  Total errors: {total_errors}")
    if all_avgs:
        lines.append(f"  Fastest avg: {min(all_avgs):.4f}s")
        lines.append(f"  Slowest avg: {max(all_avgs):.4f}s")
        lines.append(f"  Overall avg: {sum(all_avgs) / len(all_avgs):.4f}s")
    lines.append("")

    # Slowest 10 endpoints
    sorted_by_avg = sorted(results, key=lambda r: r["stats"]["avg"], reverse=True)
    lines.append("--- TOP 10 SLOWEST (by avg) ---")
    lines.append(f"  {'Endpoint':<50} {'Avg':>8} {'P95':>8}")
    lines.append(f"  {'-' * 66}")
    for r in sorted_by_avg[:10]:
        s = r["stats"]
        lines.append(f"  {r['endpoint']:<50} {s['avg']:>7.4f}s {s['p95']:>7.4f}s")
    lines.append("")
    lines.append("=" * 78)

    report_text = "\n".join(lines)
    with report_path.open("w") as f:
        f.write(report_text)

    print(f"Report written to {report_path}")
    print()
    print(report_text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Discogsography API Performance Test")
    parser.add_argument(
        "--config",
        default="/config/config.yaml",
        help="Path to YAML config file (default: /config/config.yaml)",
    )
    parser.add_argument(
        "--output",
        default="/results",
        help="Output directory for results (default: /results)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    iterations = config.get("iterations", 3)
    timeout = config.get("timeout", 30)
    base_url = config["api_base_url"]

    # Verify output directory is writable before running tests
    _verify_output_dir(Path(args.output))

    # Wait for API to be healthy
    if not wait_for_health(
        config["health_url"],
        config.get("health_retries", 30),
        config.get("health_interval", 5),
        timeout,
    ):
        print("ERROR: API did not become healthy. Exiting.")
        sys.exit(1)

    print()
    print(
        f"Config loaded: {len(config.get('artists', []))} artists, "
        f"{len(config.get('genres', []))} genres, "
        f"{len(config.get('styles', []))} styles, "
        f"{len(config.get('labels', []))} labels"
    )
    print(f"Iterations per endpoint: {iterations}")
    print()

    client = httpx.Client(timeout=timeout)

    # Resolve IDs for endpoints that need them
    print("Resolving artist IDs...")
    artist_ids = resolve_ids(client, base_url, config.get("artists", []), "artist")
    for name, aid in artist_ids.items():
        print(f"  {name} -> {aid}")

    print("Resolving label IDs...")
    label_ids = resolve_ids(client, base_url, config.get("labels", []), "label")
    for name, lid in label_ids.items():
        print(f"  {name} -> {lid}")
    print()

    # Collect database indexes
    print("Collecting database indexes...")
    neo4j_indexes = list_neo4j_indexes(config)
    postgres_indexes = list_postgres_indexes(config)
    print(f"  Neo4j: {len(neo4j_indexes) - 2} indexes")
    print(f"  PostgreSQL: {len(postgres_indexes) - 2} indexes")
    print()

    # Build test plan
    test_plan = build_test_plan(config, artist_ids, label_ids)
    print(f"Test plan: {len(test_plan)} endpoints")
    print()

    # Execute tests
    results: list[dict[str, Any]] = []
    for i, test in enumerate(test_plan, 1):
        print(f"[{i}/{len(test_plan)}] {test['name']}")
        result = run_endpoint(client, test["name"], test["url"], test["params"], iterations)
        results.append(result)
        print()

    client.close()

    # Write results
    write_report(
        results,
        Path(args.output),
        neo4j_indexes=neo4j_indexes,
        postgres_indexes=postgres_indexes,
    )


if __name__ == "__main__":
    main()
