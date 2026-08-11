"""Deploy-config regression tests for discogsography-q31w.

Both api and insights default INSIGHTS_INTERNAL_SECRET to the repo-committed
literal "dev-internal-insights-secret-change-in-production" in
docker-compose.yml. Every OTHER secret gets a docker-compose.prod.yml _FILE
override — this one didn't, so a documented-path prod deploy left
/api/internal/insights/* (reachable through the public explore proxy) gated
only by a value published in source control.
"""

from __future__ import annotations

from pathlib import Path

from tests.deploy.test_docker_compose_prod import _base_compose, _prod_compose


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestBaseInsightsSecretIsPubliclyKnownByDefault:
    """Document the vulnerable baseline so a regression in the prod fix is obvious."""

    def test_base_api_defaults_to_dev_secret(self) -> None:
        api = _base_compose()["services"]["api"]
        assert "dev-internal-insights-secret-change-in-production" in api["environment"]["INSIGHTS_INTERNAL_SECRET"]

    def test_base_insights_defaults_to_dev_secret(self) -> None:
        insights = _base_compose()["services"]["insights"]
        assert "dev-internal-insights-secret-change-in-production" in insights["environment"]["INSIGHTS_INTERNAL_SECRET"]


class TestProdInsightsInternalSecret:
    def test_secret_declared(self) -> None:
        prod = _prod_compose()
        assert "insights_internal_secret" in prod["secrets"]
        assert prod["secrets"]["insights_internal_secret"]["file"] == "./secrets/insights_internal_secret.txt"

    def test_secrets_example_placeholder_exists(self) -> None:
        assert (REPO_ROOT / "secrets.example" / "insights_internal_secret.txt").exists()

    def test_api_wires_insights_internal_secret_file(self) -> None:
        api = _prod_compose()["services"]["api"]
        assert api["environment"]["INSIGHTS_INTERNAL_SECRET_FILE"] == "/run/secrets/insights_internal_secret"
        assert "insights_internal_secret" in api["secrets"]

    def test_insights_wires_insights_internal_secret_file(self) -> None:
        insights = _prod_compose()["services"]["insights"]
        assert insights["environment"]["INSIGHTS_INTERNAL_SECRET_FILE"] == "/run/secrets/insights_internal_secret"
        assert "insights_internal_secret" in insights["secrets"]

    def test_api_and_insights_reference_the_same_secret_file(self) -> None:
        """api and insights compare this secret via secrets.compare_digest() — they
        MUST resolve to the same underlying file or every insights call would 403.
        Both services mounting the top-level `insights_internal_secret` secret
        (which resolves to a single file) is exactly that guarantee.
        """
        prod = _prod_compose()
        assert prod["secrets"]["insights_internal_secret"]["file"] == "./secrets/insights_internal_secret.txt"
        assert "insights_internal_secret" in prod["services"]["api"]["secrets"]
        assert "insights_internal_secret" in prod["services"]["insights"]["secrets"]


class TestCreateSecretsGeneratesInsightsInternalSecret:
    def test_script_references_the_secret_file(self) -> None:
        script_text = (REPO_ROOT / "scripts" / "create-secrets.sh").read_text()
        assert "insights_internal_secret.txt" in script_text
