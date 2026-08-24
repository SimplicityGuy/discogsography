"""Regression tests for discogsography-p386.

The base neo4j healthcheck authenticates with the literal dev password
(``cypher-shell -u neo4j -p discogsography``), and docker-compose.prod.yml
overrode the entrypoint, memory, and JVM settings but never the healthcheck.
In prod the real password is random — ``scripts/create-secrets.sh`` writes
``openssl rand -base64 24`` and ``scripts/neo4j-entrypoint.sh`` exports
``NEO4J_AUTH=neo4j/<secret>`` — so the inherited check failed authentication on
every attempt. Neo4j never turned ``healthy``, schema-init (gated on
``neo4j: service_healthy``) never ran, and every service gated on schema-init
(api, graphinator, brainzgraphinator, dashboard) deadlocked at boot.

These tests assert the healthcheck credential always comes from the same source
as the running server's password: the mounted secret in prod, the matching
literal in dev.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from tests.deploy.test_docker_compose_prod import _load_compose


REPO_ROOT = Path(__file__).parent.parent.parent
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"

NEO4J_PASSWORD_SECRET_PATH = "/run/secrets/neo4j_password"


def _compose(path: Path) -> dict[str, Any]:
    return _load_compose(path)


def _healthcheck_test(service: dict[str, Any]) -> list[str] | str | None:
    healthcheck = service.get("healthcheck") or {}
    test: list[str] | str | None = healthcheck.get("test")
    return test


def _healthcheck_text(service: dict[str, Any]) -> str:
    test = _healthcheck_test(service)
    if test is None:
        return ""
    return " ".join(test) if isinstance(test, list) else str(test)


def test_prod_neo4j_overrides_the_healthcheck() -> None:
    """Prod must not inherit the base check — the base credential is wrong there."""
    neo4j = _compose(PROD_COMPOSE)["services"]["neo4j"]

    assert _healthcheck_test(neo4j) is not None, (
        "docker-compose.prod.yml must override the neo4j healthcheck; the inherited one uses the dev password"
    )


def test_prod_neo4j_healthcheck_reads_the_mounted_secret() -> None:
    """The probe must authenticate with the same secret the server was seeded from."""
    neo4j = _compose(PROD_COMPOSE)["services"]["neo4j"]
    text = _healthcheck_text(neo4j)

    assert NEO4J_PASSWORD_SECRET_PATH in text, f"prod neo4j healthcheck must read {NEO4J_PASSWORD_SECRET_PATH}, got: {text!r}"
    assert "CMD-SHELL" in text, "reading the secret requires a shell form (CMD-SHELL), not exec form"


def test_prod_neo4j_healthcheck_has_no_hardcoded_password() -> None:
    """The literal dev password must not appear anywhere in the prod probe."""
    neo4j = _compose(PROD_COMPOSE)["services"]["neo4j"]
    text = _healthcheck_text(neo4j)

    assert "discogsography" not in text, f"prod neo4j healthcheck must not hardcode a password — prod auth uses a random secret: {text!r}"


def test_prod_neo4j_mounts_the_password_secret_it_probes_with() -> None:
    """A probe reading /run/secrets/neo4j_password needs that secret mounted."""
    neo4j = _compose(PROD_COMPOSE)["services"]["neo4j"]

    entries = neo4j.get("secrets") or []
    names = {entry if isinstance(entry, str) else entry.get("source", "") for entry in entries}

    assert "neo4j_password" in names, "prod neo4j must mount the neo4j_password secret its healthcheck reads"


def test_no_prod_healthcheck_hardcodes_a_credential() -> None:
    """Sweep: no prod service may embed the dev-default credential in a probe."""
    offenders = [
        name for name, service in (_compose(PROD_COMPOSE).get("services") or {}).items() if "discogsography" in _healthcheck_text(service or {})
    ]

    assert not offenders, f"prod healthchecks must source credentials from secrets, not literals: {offenders}"


def test_base_neo4j_healthcheck_matches_its_own_auth_literal() -> None:
    """In dev the literal is fine — but only while it matches NEO4J_AUTH.

    This pins the invariant that made prod break: the probe credential and the
    server credential must come from the same place.
    """
    neo4j = _compose(BASE_COMPOSE)["services"]["neo4j"]

    auth = str(neo4j["environment"]["NEO4J_AUTH"])
    _, _, auth_password = auth.partition("/")

    test = _healthcheck_test(neo4j)
    assert isinstance(test, list), "base neo4j healthcheck is expected to use the exec (list) form"
    probe_password = test[test.index("-p") + 1] if "-p" in test else ""
    if not probe_password:
        match = re.search(r"-p\s+\"?([^\"\s]+)", " ".join(test))
        probe_password = match.group(1) if match else ""

    assert probe_password == auth_password, f"base neo4j healthcheck probes with {probe_password!r} but NEO4J_AUTH sets {auth_password!r}"
