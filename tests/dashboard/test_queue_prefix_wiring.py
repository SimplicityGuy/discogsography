"""Regression tests for discogsography-dvmi.

Every component derives queue/exchange names from DISCOGS_EXCHANGE_PREFIX /
MUSICBRAINZ_EXCHANGE_PREFIX (CLAUDE.md: "never hardcode exchange names"). The
dashboard was the sole exception: PIPELINE_CONFIGS carried the default literals, so
under an override its RabbitMQ management-API filter matched nothing and both
pipeline panes silently reported an empty, healthy-looking pipeline.

`get_queue_info` logs nothing on a 200 that matches zero queues, so nothing in the
default test suite could distinguish a correct env read from a hardcoded literal —
hence the source-level assertions below, which are the negative test that was missing.
"""

from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.catalog_contract import DISCOGS_EXCHANGE_PREFIX, MUSICBRAINZ_EXCHANGE_PREFIX
from dashboard.dashboard import PIPELINE_CONFIGS


REPO_ROOT = Path(__file__).parent.parent.parent
DASHBOARD_PY = REPO_ROOT / "dashboard" / "dashboard.py"
SYSTEM_MONITOR_PY = REPO_ROOT / "utilities" / "system_monitor.py"

# Matches a *string literal* containing a default prefix. Comments (which legitimately
# name the env vars and the historical literals) are stripped before matching.
_DEFAULT_PREFIX_LITERAL = re.compile(r"""["'][^"']*discogsography-(?:discogs|musicbrainz)[^"']*["']""")


def _code_without_comments(path: Path) -> str:
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))


class TestPipelineConfigsUseEnvPrefixes:
    """PIPELINE_CONFIGS must carry the env-derived prefixes, not their defaults."""

    def test_discogs_prefix_is_the_shared_constant(self) -> None:
        assert PIPELINE_CONFIGS["discogs"]["queue_prefix"] == DISCOGS_EXCHANGE_PREFIX

    def test_musicbrainz_prefix_is_the_shared_constant(self) -> None:
        assert PIPELINE_CONFIGS["musicbrainz"]["queue_prefix"] == MUSICBRAINZ_EXCHANGE_PREFIX

    def test_dashboard_source_has_no_hardcoded_prefix_literal(self) -> None:
        """Equality against the constant passes trivially when the env var is unset, so
        also assert no default-prefix literal survives in the source at all."""
        found = _DEFAULT_PREFIX_LITERAL.findall(_code_without_comments(DASHBOARD_PY))
        assert not found, f"dashboard.py must derive queue prefixes from the environment; found literals: {found}"

    def test_system_monitor_source_has_no_hardcoded_prefix_literal(self) -> None:
        found = _DEFAULT_PREFIX_LITERAL.findall(_code_without_comments(SYSTEM_MONITOR_PY))
        assert not found, f"system_monitor.py must derive queue prefixes from the environment; found literals: {found}"


class TestQueuePrefixesEndpoint:
    """admin.js builds DLQ names the API validates against its own env-derived list,
    so the frontend has to be told the live prefixes rather than compiling them in."""

    def test_endpoint_serves_the_env_derived_prefixes(
        self,
        mock_dashboard_config: Any,
        dashboard_mock_amqp_connection: Any,
        dashboard_mock_neo4j_driver: Any,
        dashboard_mock_psycopg_connect: Any,
    ) -> None:
        with (
            patch("dashboard.dashboard.get_config", return_value=mock_dashboard_config),
            patch("dashboard.dashboard.AsyncResilientRabbitMQ", return_value=dashboard_mock_amqp_connection),
            patch("dashboard.dashboard.AsyncResilientNeo4jDriver", return_value=dashboard_mock_neo4j_driver),
            patch("dashboard.dashboard.AsyncResilientPostgreSQL", return_value=dashboard_mock_psycopg_connect),
        ):
            from dashboard.dashboard import app

            response = TestClient(app, raise_server_exceptions=False).get("/api/queue-prefixes")

        assert response.status_code == 200
        assert response.json() == {"discogs": DISCOGS_EXCHANGE_PREFIX, "musicbrainz": MUSICBRAINZ_EXCHANGE_PREFIX}


class TestAdminJsPrefixesAreOverridable:
    """The admin frontend may keep the defaults as a fallback, but must refresh them
    from the server before rendering DLQ names."""

    def test_admin_js_fetches_queue_prefixes(self) -> None:
        source = (REPO_ROOT / "dashboard" / "static" / "admin.js").read_text(encoding="utf-8")
        assert "/api/queue-prefixes" in source, "admin.js must fetch the live prefixes"
        assert "loadQueuePrefixes()" in source, "the fetched prefixes must actually be applied before rendering"
