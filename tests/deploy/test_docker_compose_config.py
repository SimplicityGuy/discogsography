"""Deploy-config regression tests for a batch of P3 config/deploy bug-hunt beads.

Covers:

- discogsography-skmw: the extractor image never honored STARTUP_DELAY (no start.sh
  shim, raw ENTRYPOINT), so the dead ``STARTUP_DELAY: "30"`` knob must not remain on
  extractor-discogs/extractor-musicbrainz — it silently did nothing and misled
  operators into believing a startup stagger existed.
- discogsography-uur3: the Python consumer images run a PID-1 shell
  (``/app/start.sh``) that sleeps ``STARTUP_DELAY`` seconds before ``exec``-ing
  python. A non-interactive shell installs no SIGTERM handler, so without an init
  process forwarding signals, a stop/restart landing in that window is silently
  ignored until Docker's SIGKILL grace period. ``init: true`` (tini as PID 1) fixes
  this uniformly for every affected service.
- discogsography-wa1x: ``just configure-discogs``'s default container name must match
  the compose ``container_name:`` the api service actually runs under.

These tests parse the compose YAML directly (no ``docker`` binary required), mirroring
the pattern in test_docker_compose_prod.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]

# Every Python service whose Dockerfile builds a /app/start.sh shim that sleeps
# STARTUP_DELAY before `exec`-ing python (i.e. runs a real PID-1 shell at startup).
# schema-init execs python directly (no shim) and extractor-* runs the raw Rust
# binary (no shim) so neither needs init: true for this reason.
PYTHON_START_SH_SERVICES = [
    "api",
    "graphinator",
    "brainzgraphinator",
    "tableinator",
    "brainztableinator",
    "dashboard",
    "explore",
    "insights",
]

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


class TestPythonServicesForwardSignalsDuringStartupDelay:
    """discogsography-uur3: init: true so SIGTERM reaches the PID-1 shell's sleep."""

    def test_start_sh_python_services_have_init_true(self) -> None:
        compose = _base_compose()
        for name in PYTHON_START_SH_SERVICES:
            assert compose["services"][name].get("init") is True, f"{name} is missing init: true"

    def test_extractor_services_do_not_need_init_true(self) -> None:
        """extractor-* run the raw binary directly (no shell/sleep at PID 1), so
        init: true is not required there — its absence is intentional, not an
        oversight of the fix-one-fix-all sweep."""
        compose = _base_compose()
        for name in EXTRACTOR_SERVICES:
            assert compose["services"][name].get("init") is not True

    def test_schema_init_does_not_need_init(self) -> None:
        """schema-init execs python directly with no start.sh shim (verified by the
        bug-hunt), so it never runs a PID-1 shell sleep either."""
        compose = _base_compose()
        assert compose["services"]["schema-init"].get("init") is not True
        dockerfile = (REPO_ROOT / "schema-init" / "Dockerfile").read_text()
        assert "start.sh" not in dockerfile


class TestConfigureDiscogsContainerDefault:
    """discogsography-wa1x: the recipe's default container must exist."""

    def test_justfile_default_matches_compose_container_name(self) -> None:
        justfile_text = (REPO_ROOT / "justfile").read_text()
        compose = _base_compose()
        api_container_name = compose["services"]["api"]["container_name"]

        assert f'container="{api_container_name}"' in justfile_text
        # Regression guard: the old default had a Compose-auto-naming "-1" suffix
        # that never matched the pinned container_name.
        assert f'container="{api_container_name}-1"' not in justfile_text
