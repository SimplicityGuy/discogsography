"""Deploy-config regression tests for discogsography-yhjn.

Base docker-compose.yml runs redis with no ``--requirepass`` and publishes
6379 to 0.0.0.0. Every OTHER stateful service (postgres, neo4j, rabbitmq) gets
a docker-compose.prod.yml hardening override that wires a Docker _FILE secret
credential — redis got none, so a prod deploy left it unauthenticated and
reachable from the network with zero credentials (FLUSHALL, cache poisoning).

These tests parse the compose YAML directly (no ``docker`` binary required)
and assert the prod overlay closes that gap: a redis_password secret exists,
the redis service authenticates with it via a custom entrypoint, the port is
rebound to loopback only, and every service that talks to redis
(api/dashboard/insights) gets REDIS_PASSWORD_FILE wired in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class _IgnoreUnknownTagsLoader(yaml.SafeLoader):
    """YAML loader that treats Compose-spec merge tags (``!override``, ``!reset``)
    as plain nodes, so we can parse docker-compose.prod.yml without teaching
    PyYAML the full Compose merge semantics — we only need the tagged node's
    own value for these assertions.
    """


def _construct_undefined(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


# PyYAML supports a None tag as the default/fallback constructor at runtime;
# the type stub only types the tag param as str, hence the ignore below.
_IgnoreUnknownTagsLoader.add_constructor(None, _construct_undefined)  # type: ignore[arg-type]


def _load_compose(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.load(path.read_text(), Loader=_IgnoreUnknownTagsLoader)  # noqa: S506 — trusted repo file, custom loader ignores unknown tags only
    return loaded


def _base_compose() -> dict[str, Any]:
    return _load_compose(REPO_ROOT / "docker-compose.yml")


def _prod_compose() -> dict[str, Any]:
    return _load_compose(REPO_ROOT / "docker-compose.prod.yml")


class TestBaseRedisIsUnauthenticatedByDefault:
    """Document the vulnerable baseline so a regression in the prod fix is obvious."""

    def test_base_redis_has_no_requirepass(self) -> None:
        redis = _base_compose()["services"]["redis"]
        assert "--requirepass" not in redis["command"]

    def test_base_redis_publishes_to_all_interfaces(self) -> None:
        redis = _base_compose()["services"]["redis"]
        ports = redis["ports"]
        assert any(str(p) == "6379:6379" for p in ports)


class TestProdRedisSecret:
    def test_redis_password_secret_declared(self) -> None:
        prod = _prod_compose()
        assert "redis_password" in prod["secrets"]
        assert prod["secrets"]["redis_password"]["file"] == "./secrets/redis_password.txt"

    def test_secrets_example_placeholder_exists(self) -> None:
        assert (REPO_ROOT / "secrets.example" / "redis_password.txt").exists()


class TestProdRedisService:
    def test_redis_service_uses_custom_entrypoint(self) -> None:
        redis = _prod_compose()["services"]["redis"]
        assert redis["entrypoint"] == ["/scripts/redis-entrypoint.sh"]

    def test_redis_service_mounts_entrypoint_script(self) -> None:
        redis = _prod_compose()["services"]["redis"]
        assert any("redis-entrypoint.sh" in str(v) for v in redis["volumes"])

    def test_redis_service_declares_password_secret(self) -> None:
        redis = _prod_compose()["services"]["redis"]
        assert "redis_password" in redis["secrets"]

    def test_redis_port_rebound_to_loopback(self) -> None:
        redis = _prod_compose()["services"]["redis"]
        ports = redis["ports"]
        assert ports == ["127.0.0.1:6379:6379"]
        assert not any(str(p) == "6379:6379" for p in ports)

    def test_redis_healthcheck_authenticates(self) -> None:
        redis = _prod_compose()["services"]["redis"]
        test_cmd = " ".join(redis["healthcheck"]["test"])
        assert "redis_password" in test_cmd
        assert "-a" in test_cmd

    def test_entrypoint_script_exists_and_is_executable(self) -> None:
        script = REPO_ROOT / "scripts" / "redis-entrypoint.sh"
        assert script.exists()
        assert script.stat().st_mode & 0o111, "redis-entrypoint.sh must be executable"


class TestProdRedisPasswordWiredIntoConsumers:
    """api, dashboard, and insights are the three services CLAUDE.md/docker-compose.yml
    document as REDIS_HOST consumers — all three must get REDIS_PASSWORD_FILE in prod,
    or they'd silently connect to the now-authenticated redis without credentials.
    """

    def test_api_gets_redis_password_file(self) -> None:
        api = _prod_compose()["services"]["api"]
        assert api["environment"]["REDIS_PASSWORD_FILE"] == "/run/secrets/redis_password"
        assert "redis_password" in api["secrets"]

    def test_dashboard_gets_redis_password_file(self) -> None:
        dashboard = _prod_compose()["services"]["dashboard"]
        assert dashboard["environment"]["REDIS_PASSWORD_FILE"] == "/run/secrets/redis_password"
        assert "redis_password" in dashboard["secrets"]

    def test_insights_gets_redis_password_file(self) -> None:
        insights = _prod_compose()["services"]["insights"]
        assert insights["environment"]["REDIS_PASSWORD_FILE"] == "/run/secrets/redis_password"
        assert "redis_password" in insights["secrets"]
