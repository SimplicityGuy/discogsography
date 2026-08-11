"""Functional test for scripts/create-secrets.sh (discogsography-yhjn).

Asserts the bootstrap script generates redis_password.txt alongside every
other prod secret — previously redis had no secret file generated at all,
so a fresh prod deploy following the documented `bash scripts/create-secrets.sh`
step left redis unauthenticated even after the docker-compose.prod.yml wiring
was added.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "create-secrets.sh"
_BASH = shutil.which("bash") or "/bin/bash"


def test_generates_redis_password_secret(tmp_path: Path) -> None:
    # The script derives SECRETS_DIR from its own location
    # ("$(dirname script)/../secrets"), so run a copy from an equivalent
    # relative layout under tmp_path to avoid touching the real repo's
    # (gitignored) secrets/ directory.
    scratch_scripts = tmp_path / "scripts"
    scratch_scripts.mkdir()
    scratch_script = scratch_scripts / "create-secrets.sh"
    shutil.copy(SCRIPT, scratch_script)
    scratch_script.chmod(0o755)

    result = subprocess.run(  # noqa: S603 — fixed args, no shell, test-controlled script
        [_BASH, str(scratch_script)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    secrets_dir = tmp_path / "secrets"
    redis_secret = secrets_dir / "redis_password.txt"
    assert redis_secret.exists()
    assert redis_secret.read_text().strip() != ""
    # Every other secret must still be generated too (no regression).
    assert (secrets_dir / "neo4j_password.txt").exists()
    assert (secrets_dir / "rabbitmq_password.txt").exists()
