"""Regression tests for independently installable shared Python packages."""

from importlib import import_module
from pathlib import Path
import tomllib
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


def _toml(relative_path: str) -> dict[str, Any]:
    with (REPO_ROOT / relative_path).open("rb") as file:
        return tomllib.load(file)


def _locked_package(name: str) -> dict[str, Any]:
    packages: list[dict[str, Any]] = _toml("uv.lock")["package"]
    return next(package for package in packages if package["name"] == name)


def test_runtime_metrics_dependency_is_optional_and_in_all() -> None:
    """The lazy metrics endpoint must be installable through a named capability."""
    extras = _toml("common/pyproject.toml")["project"]["optional-dependencies"]

    assert extras["metrics"] == ["prometheus-client>=0.26.0"]
    assert "prometheus-client>=0.26.0" in extras["all"]

    locked_extras = _locked_package("groovemap-runtime")["optional-dependencies"]
    assert locked_extras["metrics"] == [{"name": "prometheus-client"}]
    assert {dependency["name"] for dependency in locked_extras["all"]} >= {"prometheus-client"}

    assert import_module("prometheus_client")
    assert import_module("common.health_server")


def test_operations_toolkit_pins_runtime_rabbitmq_capability() -> None:
    """The queue inspection CLI must not rely on a parent environment for pika."""
    dependencies = _toml("utilities/pyproject.toml")["project"]["dependencies"]
    assert "groovemap-runtime[rabbitmq]==0.1.0" in dependencies
    assert "groovemap-runtime==0.1.0" not in dependencies

    locked_dependencies = _locked_package("groovemap-operations-toolkit")["dependencies"]
    runtime = next(dependency for dependency in locked_dependencies if dependency["name"] == "groovemap-runtime")
    assert runtime["extra"] == ["rabbitmq"]

    assert import_module("pika")
    assert import_module("utilities.debug_message")
