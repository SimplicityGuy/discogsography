"""E2E: the Ask pill expands, submits, and applies actions to the graph."""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest


@pytest.mark.e2e
def test_ask_pill_collapsed_to_submit_to_graph_mutation(page: Page, explore_url: str) -> None:
    """Test Ask pill expand-submit-apply flow end-to-end."""
    page.goto(explore_url)

    # Verify collapsed pill is visible
    pill = page.locator('[data-testid="nlq-pill-collapsed"]')
    expect(pill).to_be_visible()

    # Click to expand
    pill.click()
    expanded = page.locator('[data-testid="nlq-pill-expanded"]')
    expect(expanded).to_be_visible()

    # Verify input is focused
    input_el = page.locator('[data-testid="nlq-pill-input"]')
    expect(input_el).to_be_focused()

    # Submit a query
    input_el.fill("What labels has Kraftwerk released on?")
    input_el.press("Enter")

    # Verify strip appears with result
    strip = page.locator('[data-testid="nlq-strip"]')
    expect(strip).to_be_visible(timeout=15_000)

    # Verify graph mutation (nodes appear)
    nodes = page.locator("#graphContainer svg g.node")
    expect(nodes.first).to_be_visible(timeout=5_000)
