"""Playwright tests for the dashboard UI."""
# mypy: disable-error-code="no-untyped-def"

import re

from playwright.sync_api import Page, expect
import pytest


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestDashboardUI:
    """Test the dashboard user interface.

    The test server is automatically started by the test_server fixture.

    To run these tests:
    uv run pytest tests/dashboard/test_dashboard_ui.py -m e2e --browser chromium
    """

    def test_dashboard_loads(self, page: Page) -> None:
        """Test that the dashboard page loads successfully."""
        dashboard_url = "http://localhost:8003"

        page.goto(dashboard_url, wait_until="domcontentloaded", timeout=10000)

        # Page title is set in <title> tag
        expect(page).to_have_title("Discogsography Dashboard")

        # New design: main heading reads "Discogsography Infrastructure"
        heading = page.locator("h1")
        expect(heading).to_have_text("Discogsography Infrastructure")

    def test_service_cards_display(self, page: Page) -> None:
        """Test that service cards are displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Each service has a dedicated card element with id="service-<name>"
        service_names = ["extractor", "graphinator", "tableinator"]
        for name in service_names:
            card = page.locator(f"#service-{name}")
            expect(card).to_be_visible(timeout=10000)

        # Each card header contains the service name as text
        for name in service_names:
            card = page.locator(f"#service-{name}")
            expect(card).to_contain_text(name.capitalize(), timeout=10000)

    def test_queue_section_display(self, page: Page) -> None:
        """Test that queue metrics sections are displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Bar chart section heading
        queue_heading = page.locator("h2", has_text="Queue Size Metrics")
        expect(queue_heading).to_be_visible(timeout=10000)

        # Processing rates section heading
        rates_heading = page.locator("h2", has_text="Processing Rates")
        expect(rates_heading).to_be_visible(timeout=10000)

        # SVG rate circles are rendered (8 total: 4 publish + 4 ack)
        rate_grid = page.locator("#processing-rates-grid")
        expect(rate_grid).to_be_visible(timeout=10000)

    def test_database_cards_display(self, page: Page) -> None:
        """Test that database cards are displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Each database has a dedicated card element
        neo4j_card = page.locator("#db-neo4j")
        expect(neo4j_card).to_be_visible(timeout=10000)

        postgresql_card = page.locator("#db-postgresql")
        expect(postgresql_card).to_be_visible(timeout=10000)

        # Check database name labels
        for name in ["Neo4j", "PostgreSQL"]:
            label = page.locator(".database-name", has_text=name)
            expect(label).to_be_visible(timeout=10000)

    def test_websocket_connection(self, page: Page) -> None:
        """Test that WebSocket connection is established."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # The connection-status widget lives in the event-log header
        connection_status = page.locator(".connection-status")
        expect(connection_status).to_be_visible(timeout=10000)

        # Status text changes to "Connected" once the WS handshake completes
        status_text = page.locator(".status-text")
        expect(status_text).to_have_text("Connected", timeout=15000)

        # Status indicator acquires the .connected class
        status_indicator = page.locator(".status-indicator")
        expect(status_indicator).to_have_class(re.compile(r"connected"), timeout=10000)

    def test_activity_log_display(self, page: Page) -> None:
        """Test that the activity log is displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Event log panel is present
        activity_log = page.locator("#activityLog")
        expect(activity_log).to_be_visible(timeout=10000)

        # Should have at least one log entry (connection message)
        log_entries = page.locator(".log-entry")
        expect(log_entries.first).to_be_visible(timeout=15000)

    def test_responsive_design(self, page: Page) -> None:
        """Test that the dashboard is responsive."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Desktop viewport
        page.set_viewport_size({"width": 1440, "height": 900})
        expect(page.locator("header")).to_be_visible(timeout=10000)

        # Mobile viewport — page should still render without errors
        page.set_viewport_size({"width": 375, "height": 667})
        expect(page.locator("#activityLog")).to_be_visible(timeout=10000)

        # Service cards remain in the DOM regardless of viewport
        expect(page.locator("#service-extractor")).to_be_visible(timeout=10000)

    def test_api_endpoints(self, page: Page) -> None:
        """Test that API endpoints are accessible."""
        dashboard_url = "http://localhost:8003"

        # Test metrics endpoint
        response = page.request.get(f"{dashboard_url}/api/metrics")
        assert response.ok
        data = response.json()
        assert "services" in data
        assert "queues" in data
        assert "databases" in data

        # Test services endpoint
        response = page.request.get(f"{dashboard_url}/api/services")
        assert response.ok
        services = response.json()
        assert isinstance(services, list)

        # Test queues endpoint
        response = page.request.get(f"{dashboard_url}/api/queues")
        assert response.ok
        queues = response.json()
        assert isinstance(queues, list)

        # Test databases endpoint
        response = page.request.get(f"{dashboard_url}/api/databases")
        assert response.ok
        databases = response.json()
        assert isinstance(databases, list)
