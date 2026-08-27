"""Generate pinned Rust/Python artifacts and fixtures from the catalog event contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = Path(__file__).resolve().parent / "catalog-events" / "v1"
CONTRACT_PATH = CONTRACT_ROOT / "contract.json"
PYTHON_CONSUMERS = (
    "api",
    "brainzgraphinator",
    "brainztableinator",
    "dashboard",
    "graphinator",
    "tableinator",
    "utilities",
)


def _render_python(contract: dict[str, Any], *, lines_after_imports: int = 0) -> str:
    sources = contract["sources"]
    consumers = contract["consumers"]
    rendered_consumers = (
        "{\n" + "".join(f'    {json.dumps(name)}: {{"source": {json.dumps(item["source"])}}},\n' for name, item in sorted(consumers.items())) + "}"
    )
    import_spacing = "\n" * lines_after_imports
    return f'''"""Generated from extractor/contracts/catalog-events/v1/contract.json; do not edit."""

from __future__ import annotations

from os import getenv
{import_spacing}
CONTRACT_NAME = {json.dumps(contract["contract"])}
CONTRACT_VERSION = {contract["version"]}
AMQP_EXCHANGE_TYPE = {json.dumps(contract["exchange"]["kind"])}
DISCOGS_DATA_TYPES = {json.dumps(sources["discogs"]["entities"])}
MUSICBRAINZ_DATA_TYPES = {json.dumps(sources["musicbrainz"]["entities"])}
DISCOGS_EXCHANGE_PREFIX = getenv(
    {json.dumps(sources["discogs"]["exchange_prefix_env"])},
    {json.dumps(sources["discogs"]["default_exchange_prefix"])},
)
MUSICBRAINZ_EXCHANGE_PREFIX = getenv(
    {json.dumps(sources["musicbrainz"]["exchange_prefix_env"])},
    {json.dumps(sources["musicbrainz"]["default_exchange_prefix"])},
)
CONSUMER_SOURCES = {rendered_consumers}

# Compatibility names used by the current services. They are generated from the
# producer-owned contract rather than independently declared by consumers.
DATA_TYPES = DISCOGS_DATA_TYPES
AMQP_QUEUE_PREFIX_GRAPHINATOR = f"{{DISCOGS_EXCHANGE_PREFIX}}-graphinator"
AMQP_QUEUE_PREFIX_TABLEINATOR = f"{{DISCOGS_EXCHANGE_PREFIX}}-tableinator"
AMQP_QUEUE_PREFIX_BRAINZGRAPHINATOR = f"{{MUSICBRAINZ_EXCHANGE_PREFIX}}-brainzgraphinator"
AMQP_QUEUE_PREFIX_BRAINZTABLEINATOR = f"{{MUSICBRAINZ_EXCHANGE_PREFIX}}-brainztableinator"


def entity_types(source: str) -> list[str]:
    """Return the entity vocabulary for a catalog source."""
    if source == "discogs":
        return DISCOGS_DATA_TYPES
    if source == "musicbrainz":
        return MUSICBRAINZ_DATA_TYPES
    raise ValueError(f"Unknown catalog source: {{source}}")


def exchange_prefix(source: str) -> str:
    """Return the environment-aware exchange prefix for a source."""
    if source == "discogs":
        return DISCOGS_EXCHANGE_PREFIX
    if source == "musicbrainz":
        return MUSICBRAINZ_EXCHANGE_PREFIX
    raise ValueError(f"Unknown catalog source: {{source}}")


def exchange_name(source: str, entity: str) -> str:
    """Build a producer-owned exchange name."""
    _require_entity(source, entity)
    return f"{{exchange_prefix(source)}}-{{entity}}"


def queue_name(consumer: str, entity: str) -> str:
    """Build a registered consumer queue name."""
    try:
        source = CONSUMER_SOURCES[consumer]["source"]
    except KeyError as exc:
        raise ValueError(f"Unknown catalog consumer: {{consumer}}") from exc
    _require_entity(source, entity)
    return f"{{exchange_prefix(source)}}-{{consumer}}-{{entity}}"


def dead_letter_exchange_name(consumer: str, entity: str) -> str:
    """Build the dead-letter exchange name for a consumer queue."""
    return f"{{queue_name(consumer, entity)}}.dlx"


def dead_letter_queue_name(consumer: str, entity: str) -> str:
    """Build the dead-letter queue name for a consumer queue."""
    return f"{{queue_name(consumer, entity)}}.dlq"


def _require_entity(source: str, entity: str) -> None:
    if entity not in entity_types(source):
        raise ValueError(f"Unknown {{source}} entity: {{entity}}")
'''


def _render_rust(contract: dict[str, Any]) -> str:
    sources = contract["sources"]
    discogs = ", ".join(json.dumps(item) for item in sources["discogs"]["entities"])
    musicbrainz = ", ".join(json.dumps(item) for item in sources["musicbrainz"]["entities"])
    return f"""// Generated from extractor/contracts/catalog-events/v1/contract.json; do not edit.

pub const CONTRACT_NAME: &str = {json.dumps(contract["contract"])};
pub const CONTRACT_VERSION: u32 = {contract["version"]};
pub const AMQP_EXCHANGE_TYPE: &str = {json.dumps(contract["exchange"]["kind"])};
pub const DEFAULT_DISCOGS_EXCHANGE_PREFIX: &str = {json.dumps(sources["discogs"]["default_exchange_prefix"])};
pub const DEFAULT_MUSICBRAINZ_EXCHANGE_PREFIX: &str = {json.dumps(sources["musicbrainz"]["default_exchange_prefix"])};
pub const DISCOGS_ENTITY_TYPES: &[&str] = &[{discogs}];
pub const MUSICBRAINZ_ENTITY_TYPES: &[&str] = &[{musicbrainz}];
"""


def _render_fixtures(contract: dict[str, Any]) -> dict[Path, str]:
    rendered: dict[Path, str] = {}
    for source, entities in contract["fixture_payloads"].items():
        for entity, payload in entities.items():
            event = {
                "type": "data",
                "id": f"contract-{source}-{entity}",
                "sha256": "",
                **payload,
            }
            rendered[CONTRACT_ROOT / "fixtures" / f"{source}-{entity}.data.json"] = json.dumps(event, indent=2, sort_keys=True) + "\n"
    rendered[CONTRACT_ROOT / "fixtures" / "file-complete.json"] = (
        json.dumps(
            {
                "data_type": "artists",
                "file": "contract-artists.xml.gz",
                "timestamp": "2000-01-01T00:00:00Z",
                "total_processed": 1,
                "type": "file_complete",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    rendered[CONTRACT_ROOT / "fixtures" / "extraction-complete.json"] = (
        json.dumps(
            {
                "record_counts": {"artists": 1},
                "started_at": "2000-01-01T00:00:00Z",
                "timestamp": "2000-01-01T00:00:01Z",
                "type": "extraction_complete",
                "version": "contract-fixture",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return rendered


def render_all() -> dict[Path, str]:
    """Return every generated path and its deterministic content."""
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    rendered = {
        REPOSITORY_ROOT / "extractor" / "src" / "generated" / "catalog_contract.rs": _render_rust(contract),
    }
    for consumer in PYTHON_CONSUMERS:
        lines_after_imports = 1 if consumer in {"api", "dashboard", "utilities"} else 0
        rendered[REPOSITORY_ROOT / consumer / "catalog_contract.py"] = _render_python(
            contract,
            lines_after_imports=lines_after_imports,
        )
    rendered.update(_render_fixtures(contract))
    return rendered


def main() -> int:
    """Generate artifacts, or verify that committed output is current."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated output differs")
    args = parser.parse_args()
    stale: list[Path] = []
    for path, content in render_all().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(REPOSITORY_ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if stale:
        sys.stderr.write("stale catalog contract artifacts:\n")
        sys.stderr.write("".join(f"  {path}\n" for path in stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
