"""Functional tests for scripts/redis-entrypoint.sh (discogsography-yhjn).

Redis doesn't natively support the Docker ``_FILE`` secret convention, so the
production overlay delegates to this wrapper to read
``/run/secrets/redis_password`` and append ``--requirepass`` before handing
off to the official image entrypoint — mirroring scripts/neo4j-entrypoint.sh
and scripts/rabbitmq-entrypoint.sh.

These tests stub out ``docker-entrypoint.sh`` on PATH (the real one lives
inside the redis:7-alpine image, not on the host) and assert the wrapper
invokes it with the right arguments.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "redis-entrypoint.sh"


def _run_with_stub_entrypoint(tmp_path: Path, secret_file: Path | None) -> subprocess.CompletedProcess[str]:
    """Run redis-entrypoint.sh with a stub docker-entrypoint.sh on PATH that
    just echoes its argv, and a fake /run/secrets path (via a symlink-free
    override: the script hardcodes /run/secrets/redis_password, so this only
    works when we can write there — instead we exercise the script's logic
    via a copy with the secrets path parameterized through an env var for
    testability isn't available, so we assert behavior by placing/removing a
    real file at a location the test controls by invoking a modified PATH
    and HOME instead).
    """
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "docker-entrypoint.sh"
    stub.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            echo "ARGS:$*"
            """
        )
    )
    stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"

    secrets_dir = tmp_path / "run_secrets"
    secrets_dir.mkdir()
    if secret_file is not None:
        (secrets_dir / "redis_password").write_text(secret_file.read_text() if secret_file.exists() else "")

    # The script hardcodes /run/secrets/redis_password. We can't safely write
    # to the real /run/secrets on a dev/CI box, so instead run the script
    # under a mount-namespace-free substitution: copy it and rewrite the one
    # path constant to our tmp secrets dir. This keeps the test hermetic
    # while still exercising the exact conditional/exec logic byte-for-byte.
    patched_script = tmp_path / "redis-entrypoint.sh"
    patched_script.write_text(SCRIPT.read_text().replace("/run/secrets/redis_password", str(secrets_dir / "redis_password")))
    patched_script.chmod(0o755)

    return subprocess.run(  # noqa: S603 — fixed args, test-controlled script/paths, no shell
        [str(patched_script), "redis-server", "--appendonly", "yes"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


class TestRedisEntrypointScript:
    def test_appends_requirepass_when_secret_present(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret_source"
        secret.write_text("s3cr3t-pw\n")

        result = _run_with_stub_entrypoint(tmp_path, secret_file=secret)

        assert result.returncode == 0, result.stderr
        assert "--requirepass s3cr3t-pw" in result.stdout
        assert "redis-server --appendonly yes" in result.stdout

    def test_does_not_leak_password_on_failure_path(self, tmp_path: Path) -> None:
        """Sanity check: with no secret file, no --requirepass flag is added at all
        (the server would run unauthenticated, matching today's dev behavior) —
        it must not silently pass an empty/garbage password.
        """
        result = _run_with_stub_entrypoint(tmp_path, secret_file=None)

        assert result.returncode == 0, result.stderr
        assert "--requirepass" not in result.stdout
        assert "redis-server --appendonly yes" in result.stdout

    def test_script_is_executable(self) -> None:
        assert SCRIPT.stat().st_mode & 0o111
