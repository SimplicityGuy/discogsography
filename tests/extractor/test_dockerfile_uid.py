"""Regression tests for discogsography-cu2.13.

The extractor image used to create its runtime user with a bare
``useradd -r`` (no ``-u``), which allocates an auto-assigned *system* UID
(<1000) — never the ``1000`` that docker-compose.yml hardcoded via
``user: "1000:1000"``. On a fresh named volume, Docker chowns the volume
root to the image's file owner (~999), so the UID-1000 runtime process
gets EACCES on its first write under /discogs-data, /musicbrainz-data, or
/logs and crash-loops, ingesting nothing.

These tests assert the extractor Dockerfile follows the same
"ARG UID/GID + useradd -u ${UID}" pattern already used by every other
service Dockerfile in this repo, and that docker-compose.yml passes
matching build args and a matching (non-hardcoded) `user:` override, so
the image-file owner and the runtime UID can never diverge again.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import yaml


REPO_ROOT = Path(__file__).parent.parent.parent
EXTRACTOR_DOCKERFILE = REPO_ROOT / "extractor" / "Dockerfile"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

# Every other service Dockerfile already follows this pattern; used as a
# reference so the extractor sweep target doesn't silently drift again.
OTHER_SERVICE_DOCKERFILES = [
    "api/Dockerfile",
    "dashboard/Dockerfile",
    "explore/Dockerfile",
    "graphinator/Dockerfile",
    "insights/Dockerfile",
    "schema-init/Dockerfile",
    "tableinator/Dockerfile",
    "brainzgraphinator/Dockerfile",
    "brainztableinator/Dockerfile",
]


def _dockerfile_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_extractor_dockerfile_declares_uid_gid_args() -> None:
    """The runtime stage must accept ARG UID / ARG GID, defaulting to 1000."""
    text = EXTRACTOR_DOCKERFILE.read_text(encoding="utf-8")

    assert re.search(r"^ARG UID=1000\s*$", text, re.MULTILINE), "extractor/Dockerfile must declare `ARG UID=1000`"
    assert re.search(r"^ARG GID=1000\s*$", text, re.MULTILINE), "extractor/Dockerfile must declare `ARG GID=1000`"


def _command_lines(text: str, keyword: str) -> list[str]:
    """Return non-comment lines that actually invoke `keyword` as a command."""
    return [line for line in text.splitlines() if re.search(rf"(^|&&|\s){re.escape(keyword)}\s", line) and not line.strip().startswith("#")]


def test_extractor_dockerfile_useradd_uses_explicit_uid() -> None:
    """useradd must pin the explicit UID — a bare `useradd -r` (no -u) is the
    exact defect: it allocates an auto-assigned system UID, not 1000."""
    text = EXTRACTOR_DOCKERFILE.read_text(encoding="utf-8")

    useradd_lines = _command_lines(text, "useradd")
    assert useradd_lines, "extractor/Dockerfile must create a runtime user via useradd"

    for line in useradd_lines:
        assert "-u ${UID}" in line, f"useradd must pin -u ${{UID}} to avoid an auto-allocated system UID: {line!r}"

    groupadd_lines = _command_lines(text, "groupadd")
    assert groupadd_lines, "extractor/Dockerfile must create a runtime group via groupadd"
    for line in groupadd_lines:
        assert "-g ${GID}" in line, f"groupadd must pin -g ${{GID}}: {line!r}"


def test_extractor_dockerfile_final_user_matches_created_account() -> None:
    """USER must select the account whose UID/GID we just pinned (not a bare
    username that could resolve differently across stages)."""
    text = EXTRACTOR_DOCKERFILE.read_text(encoding="utf-8")

    assert re.search(r"^USER extractor:extractor\s*$", text, re.MULTILINE), (
        "extractor/Dockerfile must `USER extractor:extractor` to match the chowned data/log dirs"
    )


def test_extractor_matches_other_service_useradd_pattern() -> None:
    """Fix-one-fix-all sanity check: every other service Dockerfile already
    uses `useradd -r -l -u ${UID} ...` — confirm the extractor now matches
    the same convention rather than introducing a new one."""
    for relative_path in OTHER_SERVICE_DOCKERFILES:
        text = _dockerfile_text(relative_path)
        useradd_lines = _command_lines(text, "useradd")
        assert useradd_lines, f"{relative_path} must create a runtime user via useradd"
        for line in useradd_lines:
            assert "-u ${UID}" in line, f"{relative_path} unexpectedly diverges from the -u ${{UID}} convention: {line!r}"

    extractor_text = EXTRACTOR_DOCKERFILE.read_text(encoding="utf-8")
    extractor_useradd = next(iter(_command_lines(extractor_text, "useradd")))
    assert "-u ${UID}" in extractor_useradd


def _load_compose_service(name: str) -> dict[str, Any]:
    with COMPOSE_FILE.open(encoding="utf-8") as f:
        compose: dict[str, Any] = yaml.safe_load(f)
    services: dict[str, Any] = compose["services"]
    result: dict[str, Any] = services[name]
    return result


def test_compose_extractor_services_pass_uid_gid_build_args() -> None:
    """docker-compose.yml must pass UID/GID build args to the extractor
    image, or the built image's file owner can never match the configured
    runtime user."""
    for service_name in ("extractor-discogs", "extractor-musicbrainz"):
        service = _load_compose_service(service_name)
        build_args = service["build"]["args"]
        assert build_args["UID"] == "${UID:-1000}", f"{service_name} build.args.UID must be parameterized"
        assert build_args["GID"] == "${GID:-1000}", f"{service_name} build.args.GID must be parameterized"


def test_compose_extractor_services_user_is_parameterized_not_hardcoded() -> None:
    """The regression: `user: "1000:1000"` was hardcoded while the image's
    useradd allocated a system UID (<1000) with no build args wired up at
    all — guaranteeing the two never matched. The user: override must now
    reference the same UID/GID vars passed as build args."""
    for service_name in ("extractor-discogs", "extractor-musicbrainz"):
        service = _load_compose_service(service_name)
        assert service["user"] == "${UID:-1000}:${GID:-1000}", (
            f"{service_name} user: must be parameterized to match build.args.UID/GID, not hardcoded"
        )
