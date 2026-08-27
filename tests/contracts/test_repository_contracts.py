"""Repository-boundary contract tests for the monorepo split."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tomllib
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import pytest
import yaml

from graphinator import catalog_contract
from insights import catalog_api_contract


if TYPE_CHECKING:
    from types import ModuleType


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = REPOSITORY_ROOT / "extractor" / "contracts" / "catalog-events" / "v1"


def _load_script(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_contract_generation_is_current() -> None:
    generator = _load_script(REPOSITORY_ROOT / "extractor" / "contracts" / "generate.py", "catalog_contract_generator")
    stale = [path for path, content in generator.render_all().items() if not path.exists() or path.read_text(encoding="utf-8") != content]
    assert not stale


def test_catalog_fixtures_match_v1_event_schema_and_vocabulary() -> None:
    contract: dict[str, Any] = json.loads((CATALOG_ROOT / "contract.json").read_text(encoding="utf-8"))
    schema = json.loads((CATALOG_ROOT / contract["event_schema"]).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    expected_data_fixtures = {
        f"{source}-{entity}.data.json" for source, source_contract in contract["sources"].items() for entity in source_contract["entities"]
    }
    actual_data_fixtures = {path.name for path in (CATALOG_ROOT / "fixtures").glob("*.data.json")}
    assert actual_data_fixtures == expected_data_fixtures
    for fixture in (CATALOG_ROOT / "fixtures").glob("*.json"):
        validator.validate(json.loads(fixture.read_text(encoding="utf-8")))
    assert (CATALOG_ROOT / contract["extraction_rules"]).is_file()


def test_queue_names_come_from_the_versioned_contract() -> None:
    assert catalog_contract.exchange_name("discogs", "artists") == "discogsography-discogs-artists"
    assert catalog_contract.queue_name("graphinator", "artists") == "discogsography-discogs-graphinator-artists"
    assert catalog_contract.dead_letter_exchange_name("brainztableinator", "release-groups").endswith(".dlx")
    assert catalog_contract.dead_letter_queue_name("brainztableinator", "release-groups").endswith(".dlq")


def test_api_consumer_artifact_matches_owned_openapi() -> None:
    generator = _load_script(REPOSITORY_ROOT / "api" / "contracts" / "generate.py", "api_contract_generator")
    output = REPOSITORY_ROOT / "insights" / "catalog_api_contract.py"
    assert output.read_text(encoding="utf-8") == generator.render()

    openapi = yaml.safe_load(generator.OPENAPI_PATH.read_text(encoding="utf-8"))
    assert set(openapi["paths"]) == {
        "/api/internal/insights/anniversaries",
        "/api/internal/insights/artist-centrality",
        "/api/internal/insights/community-enrichment",
        "/api/internal/insights/data-completeness",
        "/api/internal/insights/genre-trends",
        "/api/internal/insights/label-longevity",
        "/api/internal/insights/rarity-scores",
    }
    router_source = (REPOSITORY_ROOT / "api" / "routers" / "insights_compute.py").read_text(encoding="utf-8")
    for path in openapi["paths"]:
        route_suffix = path.removeprefix("/api/internal/insights")
        assert f'@router.get("{route_suffix}")' in router_source

    generated_paths = {value for name, value in vars(catalog_api_contract).items() if name.endswith("_PATH")}
    assert generated_paths == set(openapi["paths"])


def test_api_query_contract_matches_live_fastapi_constraints() -> None:
    """Keep the versioned query surface aligned with FastAPI's current routes."""
    from api.api import app

    contract = yaml.safe_load((REPOSITORY_ROOT / "api" / "contracts" / "internal-insights" / "v1" / "openapi.yaml").read_text(encoding="utf-8"))
    live = app.openapi()

    def normalize(parameter: dict[str, Any]) -> dict[str, Any]:
        schema = parameter["schema"]
        return {
            "name": parameter["name"],
            "in": parameter["in"],
            "required": parameter.get("required", False),
            "schema": {key: schema[key] for key in ("type", "minimum", "maximum", "default") if key in schema},
        }

    for path, path_item in contract["paths"].items():
        contract_parameters = []
        for parameter in path_item["get"].get("parameters", []):
            reference = parameter["$ref"].rsplit("/", maxsplit=1)[-1]
            contract_parameters.append(normalize(contract["components"]["parameters"][reference]))
        live_parameters = [normalize(parameter) for parameter in live["paths"][path]["get"].get("parameters", []) if parameter["in"] == "query"]
        assert contract_parameters == live_parameters, path


def test_community_enrichment_contract_matches_route_and_consumer_shape() -> None:
    contract = yaml.safe_load((REPOSITORY_ROOT / "api" / "contracts" / "internal-insights" / "v1" / "openapi.yaml").read_text(encoding="utf-8"))
    operation = contract["paths"][catalog_api_contract.COMMUNITY_ENRICHMENT_PATH]["get"]
    assert operation["responses"]["200"]["$ref"] == "#/components/responses/CommunityEnrichment"

    schema = contract["components"]["schemas"]["CommunityEnrichmentResult"]
    validator = Draft202012Validator(schema)
    validator.validate({"enriched": 3, "skipped": 1, "errors": 0, "remaining": 7})
    validator.validate({"enriched": 0, "skipped": 4, "errors": 0, "remaining": 2, "error": "no_credentials"})

    with pytest.raises(ValidationError):
        validator.validate({"items": []})


def test_cross_repository_tests_have_an_extraction_owner() -> None:
    manifest = tomllib.loads((REPOSITORY_ROOT / "tests" / "repository-ownership.toml").read_text(encoding="utf-8"))
    assignments = manifest["assignment"]
    assert assignments
    for assignment in assignments:
        assert assignment["owner"] in {"catalog-api", "deployment"}
        for path in assignment["paths"]:
            assert (REPOSITORY_ROOT / path).is_file(), path


def test_persistence_contract_points_at_schema_sources() -> None:
    path = REPOSITORY_ROOT / "schema-init" / "contracts" / "persistence" / "v1" / "compatibility.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    assert contract["owners"] == ["database-schema"]
    for source in contract["sources"]:
        assert (REPOSITORY_ROOT / "schema-init" / source).is_file()
