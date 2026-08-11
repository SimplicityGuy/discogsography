"""Regression test for discogsography-da2o.

.env.example documented a dead variable name, OAUTH_ENCRYPTION_KEY, with a
comment promising it encrypts Discogs OAuth tokens/consumer keys at rest. No
production code ever read that name — common/config.py and api/setup.py only
read ENCRYPTION_MASTER_KEY (the codebase migrated from a Fernet
OAUTH_ENCRYPTION_KEY to an HKDF-derived ENCRYPTION_MASTER_KEY — see
scripts/migrate-encryption-key.sh). An operator following .env.example
literally would set a value that is silently ignored, leaving OAuth tokens
and TOTP secrets stored in plaintext despite the file's own warning that this
is exactly what happens "if unset".
"""

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _env_example_text() -> str:
    return ENV_EXAMPLE.read_text()


def test_does_not_document_the_dead_oauth_encryption_key_var() -> None:
    assert "OAUTH_ENCRYPTION_KEY" not in _env_example_text()


def test_documents_encryption_master_key_instead() -> None:
    text = _env_example_text()
    assert re.search(r"^ENCRYPTION_MASTER_KEY=", text, re.MULTILINE), (
        ".env.example must set ENCRYPTION_MASTER_KEY (the var name common/config.py actually reads)"
    )


def test_env_example_var_names_are_all_read_by_config_or_documented_elsewhere() -> None:
    """The var this bead renamed (ENCRYPTION_MASTER_KEY) must be one that
    common/config.py's get_secret() convention actually consults — i.e. it
    isn't itself a new dead var.
    """
    config_text = (REPO_ROOT / "common" / "config.py").read_text()
    assert 'get_secret("ENCRYPTION_MASTER_KEY")' in config_text


def test_migrate_encryption_key_script_still_references_old_name() -> None:
    """scripts/migrate-encryption-key.sh's entire purpose is migrating
    OAUTH_ENCRYPTION_KEY -> ENCRYPTION_MASTER_KEY for existing deployments —
    it must keep referencing the old name (unlike .env.example, which should
    only ever tell NEW operators about the current name).
    """
    script = REPO_ROOT / "scripts" / "migrate-encryption-key.sh"
    assert script.exists()
    assert "OAUTH_ENCRYPTION_KEY" in script.read_text()
