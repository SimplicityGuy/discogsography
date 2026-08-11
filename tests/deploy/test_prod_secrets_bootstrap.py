"""Regression tests for discogsography-edez.

``docker-compose.prod.yml`` declared ``nlq_api_key`` as a file-backed secret
(``./secrets/nlq_api_key.txt``) and listed it under the ``api`` service, but
neither documented bootstrap path produced that file: ``scripts/create-secrets.sh``
never wrote it and ``secrets.example/`` never shipped a placeholder. Docker
Compose materializes a file secret when creating the container that references
it, so the api service — the sole owner of every user-facing HTTP endpoint —
failed to start with "file not found for secret" on a by-the-book prod deploy,
for a feature that is disabled by default.

These tests pin the invariant generically: every file-backed secret declared in
the production overlay must be created by ``scripts/create-secrets.sh`` and have
a reference placeholder in ``secrets.example/``, and every secret a service
consumes must be declared at the top level.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml


REPO_ROOT = Path(__file__).parent.parent.parent
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
CREATE_SECRETS = REPO_ROOT / "scripts" / "create-secrets.sh"
SECRETS_EXAMPLE = REPO_ROOT / "secrets.example"


def _prod_compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))
    return data


def _declared_file_secrets() -> dict[str, str]:
    """Map top-level secret name -> the ``file:`` path it is sourced from."""
    secrets: dict[str, Any] = _prod_compose().get("secrets", {}) or {}
    return {name: spec["file"] for name, spec in secrets.items() if isinstance(spec, dict) and "file" in spec}


def _service_secret_refs() -> dict[str, list[str]]:
    """Map service name -> the list of secret names it consumes."""
    services: dict[str, Any] = _prod_compose().get("services", {}) or {}
    refs: dict[str, list[str]] = {}
    for service, spec in services.items():
        entries = (spec or {}).get("secrets") or []
        names = [entry if isinstance(entry, str) else entry.get("source", "") for entry in entries]
        if names:
            refs[service] = names
    return refs


def _bootstrapped_secret_files() -> set[str]:
    """Filenames that ``scripts/create-secrets.sh`` writes via ``write_secret``."""
    text = CREATE_SECRETS.read_text(encoding="utf-8")
    written: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        match = re.match(r'write_secret\s+"([^"]+)"', stripped)
        if match:
            written.add(match.group(1))
    return written


def test_prod_file_secrets_are_created_by_bootstrap_script() -> None:
    """Every file-backed prod secret must be produced by create-secrets.sh.

    A missing writer aborts container creation for any service that mounts the
    secret — this is exactly how nlq_api_key broke the api service.
    """
    written = _bootstrapped_secret_files()

    missing = {name: path for name, path in _declared_file_secrets().items() if Path(path).name not in written}

    assert not missing, f"docker-compose.prod.yml declares file secrets that scripts/create-secrets.sh never writes: {sorted(missing)}"


def test_prod_file_secrets_have_example_placeholders() -> None:
    """secrets.example/ must ship a reference placeholder for each prod secret."""
    available = {path.name for path in SECRETS_EXAMPLE.iterdir() if path.is_file()}

    missing = {name: Path(path).name for name, path in _declared_file_secrets().items() if Path(path).name not in available}

    assert not missing, f"docker-compose.prod.yml declares file secrets with no secrets.example/ placeholder: {sorted(missing)}"


def test_service_secret_references_are_declared() -> None:
    """A service may only consume secrets declared in the top-level block."""
    declared = set(_prod_compose().get("secrets", {}) or {})

    for service, names in _service_secret_refs().items():
        undeclared = sorted(set(names) - declared)
        assert not undeclared, f"service {service!r} references undeclared secrets: {undeclared}"


def test_nlq_api_key_secret_is_bootstrapped() -> None:
    """Explicit pin on the original defect site."""
    assert "nlq_api_key.txt" in _bootstrapped_secret_files(), (
        "scripts/create-secrets.sh must write nlq_api_key.txt — prod's api service mounts it as a required secret"
    )
    assert (SECRETS_EXAMPLE / "nlq_api_key.txt").is_file(), "secrets.example/nlq_api_key.txt must exist as a reference placeholder"


def test_optional_secrets_default_to_empty() -> None:
    """Optional keys (resend, nlq) must be written even when the env var is unset.

    ``write_secret "<name>" "${VAR:-}"`` is the established pattern: the file
    always exists so compose is satisfied, and empty content leaves the feature
    disabled.
    """
    text = CREATE_SECRETS.read_text(encoding="utf-8")

    for filename, env_var in (("resend_api_key.txt", "RESEND_API_KEY"), ("nlq_api_key.txt", "NLQ_API_KEY")):
        pattern = rf'write_secret\s+"{re.escape(filename)}"\s+"\$\{{{env_var}:-\}}"'
        assert re.search(pattern, text), (
            f"create-secrets.sh must write {filename} from ${{{env_var}:-}} so the file exists even when the feature is off"
        )
