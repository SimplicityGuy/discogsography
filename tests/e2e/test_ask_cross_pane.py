"""E2E: an Ask query that triggers switch_pane should navigate and render."""

from __future__ import annotations

from playwright.sync_api import Page, expect
import pytest


@pytest.mark.e2e
def test_ask_switch_pane_to_insights(page: Page, explore_url: str) -> None:
    page.goto(explore_url)
    page.locator('[data-testid="nlq-pill-collapsed"]').click()
    input_el = page.locator('[data-testid="nlq-pill-input"]')
    input_el.fill("Show me the biggest labels of 2024")
    input_el.press("Enter")

    expect(page.locator('[data-testid="nlq-strip"]')).to_be_visible(timeout=15_000)

    insights_link = page.locator('.nav-link[data-pane="insights"].active')
    expect(insights_link).to_be_visible(timeout=5_000)
