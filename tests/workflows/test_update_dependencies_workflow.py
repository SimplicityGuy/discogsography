"""Regression tests for .github/workflows/update-dependencies.yml.

Covers discogsography-cu2.69: the automated dependency-update PR was opened with the
default GITHUB_TOKEN, which GitHub Actions excludes from triggering new workflow runs
(recursion prevention) — so build.yml's `pull_request` trigger never fired and the PR
shipped with zero CI checks, contradicting the PR body's "tests have been run
automatically" / "check CI status" claims.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "update-dependencies.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    with WORKFLOW_PATH.open() as f:
        return yaml.safe_load(f)


def _create_pr_step(workflow_data: dict[str, Any]) -> dict[str, Any]:
    steps = workflow_data["jobs"]["update-dependencies"]["steps"]
    for step in steps:
        if "Create Pull Request" in step.get("name", ""):
            return step
    raise AssertionError("Create Pull Request step not found in update-dependencies.yml")


class TestCreatePullRequestToken:
    """The PR-creation step must not rely solely on the default GITHUB_TOKEN."""

    def test_token_prefers_a_pat_over_the_default_github_token(self, workflow: dict[str, Any]) -> None:
        token_expr = _create_pr_step(workflow)["with"]["token"]

        # A bare `${{ secrets.GITHUB_TOKEN }}` never triggers new workflow runs on the
        # PR it opens (GitHub's recursion-prevention rule) — the expression must name a
        # PAT/App-token secret ahead of the GITHUB_TOKEN fallback.
        assert token_expr != "${{ secrets.GITHUB_TOKEN }}"
        assert "secrets.GITHUB_TOKEN" not in token_expr.split("||")[0], (
            "the first alternative in the token expression must be a dedicated PAT secret, not GITHUB_TOKEN"
        )
        assert "secrets." in token_expr

    def test_token_still_falls_back_to_github_token(self, workflow: dict[str, Any]) -> None:
        """If the PAT secret is unset, the step must still work (degrade to no-CI, not fail)."""
        token_expr = _create_pr_step(workflow)["with"]["token"]
        assert "secrets.GITHUB_TOKEN" in token_expr


class TestPullRequestBodyIsNotMisleading:
    """The PR body must not assert CI guarantees the workflow cannot provide."""

    def test_body_does_not_claim_unqualified_automatic_test_success(self, workflow: dict[str, Any]) -> None:
        body = _create_pr_step(workflow)["with"]["body"]
        # The old body asserted "Tests have been run automatically" without qualifying
        # that failures are only warned about, not blocking — misleading a reviewer who
        # trusts the claim at face value.
        assert "Tests have been run automatically" not in body
