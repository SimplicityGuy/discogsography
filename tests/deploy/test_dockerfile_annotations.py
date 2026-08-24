"""Regression tests for actionable Dockerfile lint annotations."""

from collections.abc import Iterator
from pathlib import Path
import re
import shlex


REPO_ROOT = Path(__file__).parent.parent.parent
RUNTIME_DOCKERFILES = (
    "api/Dockerfile",
    "brainzgraphinator/Dockerfile",
    "brainztableinator/Dockerfile",
    "dashboard/Dockerfile",
    "explore/Dockerfile",
    "extractor/Dockerfile",
    "graphinator/Dockerfile",
    "insights/Dockerfile",
    "schema-init/Dockerfile",
    "tableinator/Dockerfile",
)
HEALTH_ENDPOINTS = {
    "api/Dockerfile": "http://localhost:8005/health",
    "brainzgraphinator/Dockerfile": "http://localhost:8011/health",
    "brainztableinator/Dockerfile": "http://localhost:8010/health",
    "dashboard/Dockerfile": "http://localhost:8003/health",
    "explore/Dockerfile": "http://localhost:8007/health",
    "extractor/Dockerfile": "http://localhost:8000/health",
    "graphinator/Dockerfile": "http://localhost:8001/health",
    "insights/Dockerfile": "http://localhost:8009/health",
    "tableinator/Dockerfile": "http://localhost:8002/health",
}
SENSITIVE_ENV_KEY = re.compile(r"(?:PASSWORD|USERNAME|SECRET|TOKEN|CREDENTIAL|PRIVATE_KEY)(?:$|_)")


def _instructions(relative_path: str) -> Iterator[str]:
    """Yield logical Dockerfile instructions with continuations joined."""
    parts: list[str] = []
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not parts and (not line or line.startswith("#")):
            continue
        continued = line.endswith("\\")
        parts.append(line.removesuffix("\\").rstrip())
        if not continued:
            yield " ".join(parts)
            parts.clear()


def test_runtime_users_use_numeric_build_arguments() -> None:
    for relative_path in RUNTIME_DOCKERFILES:
        instructions = tuple(_instructions(relative_path))
        assert "USER ${UID}:${GID}" in instructions, f"{relative_path} must use its numeric build-time UID/GID"


def test_healthchecks_use_exec_form() -> None:
    for relative_path, endpoint in HEALTH_ENDPOINTS.items():
        healthcheck = next(instruction for instruction in _instructions(relative_path) if instruction.startswith("HEALTHCHECK "))
        assert f'CMD ["curl", "-f", "{endpoint}"]' in healthcheck, f"{relative_path} healthcheck must use JSON exec form"


def test_images_do_not_persist_credential_placeholders() -> None:
    for relative_path in RUNTIME_DOCKERFILES:
        for instruction in _instructions(relative_path):
            if not instruction.startswith("ENV "):
                continue
            keys = (assignment.split("=", 1)[0] for assignment in shlex.split(instruction.removeprefix("ENV ")))
            sensitive_keys = [key for key in keys if SENSITIVE_ENV_KEY.search(key)]
            assert not sensitive_keys, f"{relative_path} persists credential-like ENV keys: {sensitive_keys}"
