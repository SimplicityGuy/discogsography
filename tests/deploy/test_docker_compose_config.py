"""Deploy-config regression tests for a batch of P3 config/deploy bug-hunt beads.

Covers:

- discogsography-skmw: the extractor image never honored STARTUP_DELAY (no start.sh
  shim, raw ENTRYPOINT), so the dead ``STARTUP_DELAY: "30"`` knob must not remain on
  extractor-discogs/extractor-musicbrainz — it silently did nothing and misled
  operators into believing a startup stagger existed.

These tests parse the compose YAML directly (no ``docker`` binary required), mirroring
the pattern in test_docker_compose_prod.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]

EXTRACTOR_SERVICES = ["extractor-discogs", "extractor-musicbrainz"]


def _load_compose(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(path.read_text())
    return loaded


def _base_compose() -> dict[str, Any]:
    return _load_compose(REPO_ROOT / "docker-compose.yml")


class TestExtractorStartupDelayRemoved:
    """discogsography-skmw: STARTUP_DELAY was dead on the extractor image."""

    def test_extractor_services_have_no_startup_delay_env(self) -> None:
        compose = _base_compose()
        for name in EXTRACTOR_SERVICES:
            env = compose["services"][name].get("environment", {}) or {}
            assert "STARTUP_DELAY" not in env, f"{name} still sets the dead STARTUP_DELAY knob"

    def test_extractor_dockerfile_has_no_start_sh_shim(self) -> None:
        """The extractor image execs the raw binary directly — confirms STARTUP_DELAY
        genuinely has no code path that would honor it, so dropping the compose
        knob (rather than implementing it) is the correct fix."""
        dockerfile = (REPO_ROOT / "extractor" / "Dockerfile").read_text()
        assert "start.sh" not in dockerfile
        assert 'ENTRYPOINT ["extractor"]' in dockerfile

    def test_extractor_rust_source_has_no_startup_delay_reference(self) -> None:
        src_dir = REPO_ROOT / "extractor" / "src"
        for path in src_dir.rglob("*.rs"):
            assert "STARTUP_DELAY" not in path.read_text(), f"{path} unexpectedly references STARTUP_DELAY"
