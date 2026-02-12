"""E2E browser tests for the Explore service UI."""

import re

from playwright.sync_api import Page, expect
import pytest


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreUI:
    """End-to-end tests for the Explore service web interface."""

    def test_page_loads(self, page: Page, test_server: str) -> None:
        """Test that the explore page loads successfully."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)
        expect(page).to_have_title(re.compile("Explore", re.IGNORECASE))

    def test_navbar_visible(self, page: Page, test_server: str) -> None:
        """Test that the navigation bar is visible."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)

        navbar = page.locator("nav")
        expect(navbar).to_be_visible(timeout=5000)

    def test_search_input_visible(self, page: Page, test_server: str) -> None:
        """Test that the search input is visible."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)

        search_input = page.locator("#searchInput")
        expect(search_input).to_be_visible(timeout=5000)

    def test_search_type_dropdown(self, page: Page, test_server: str) -> None:
        """Test the search type dropdown works."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)

        # Find the search type button
        type_btn = page.locator("#searchTypeBtn")
        expect(type_btn).to_be_visible(timeout=5000)
        expect(type_btn).to_have_text("Artist")

    def test_pane_switching(self, page: Page, test_server: str) -> None:
        """Test switching between Explore and Trends panes."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)

        # Explore pane should be active by default
        explore_pane = page.locator("#explorePane")
        expect(explore_pane).to_have_class(re.compile("active"), timeout=5000)

        # Click Trends tab
        trends_link = page.locator("[data-pane='trends']")
        trends_link.click()

        # Trends pane should now be active
        trends_pane = page.locator("#trendsPane")
        expect(trends_pane).to_have_class(re.compile("active"), timeout=5000)

        # Click Explore tab again
        explore_link = page.locator("[data-pane='explore']")
        explore_link.click()
        expect(explore_pane).to_have_class(re.compile("active"), timeout=5000)

    def test_graph_placeholder_visible(self, page: Page, test_server: str) -> None:
        """Test that the graph placeholder is shown before search."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)

        placeholder = page.locator("#graphPlaceholder")
        expect(placeholder).to_be_visible(timeout=5000)

    def test_health_endpoint(self, page: Page, test_server: str) -> None:
        """Test the health API endpoint from browser."""
        response = page.request.get(f"{test_server}/health")
        assert response.ok
        data = response.json()
        assert data["service"] == "explore"
        assert data["status"] == "healthy"

    def test_responsive_layout(self, page: Page, test_server: str) -> None:
        """Test that the page responds to viewport changes."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)

        # Desktop viewport
        page.set_viewport_size({"width": 1280, "height": 720})
        search_input = page.locator("#searchInput")
        expect(search_input).to_be_visible(timeout=5000)

        # Mobile viewport
        page.set_viewport_size({"width": 375, "height": 667})
        expect(search_input).to_be_visible(timeout=5000)

    def test_info_panel_hidden_by_default(self, page: Page, test_server: str) -> None:
        """Test that the info panel is hidden before any node is clicked."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=10000)

        info_panel = page.locator("#infoPanel")
        # The panel exists but should not have the 'open' class
        expect(info_panel).not_to_have_class(re.compile("open"), timeout=5000)
