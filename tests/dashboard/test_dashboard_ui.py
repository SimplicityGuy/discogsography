"""Playwright tests for the dashboard UI."""
# mypy: disable-error-code="no-untyped-def"

import re

import pytest
from playwright.sync_api import Page, expect


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

        # Navigate to the dashboard
        page.goto(dashboard_url, wait_until="domcontentloaded", timeout=10000)

        # Check page title
        expect(page).to_have_title("Discogsography Dashboard")

        # Check main heading
        heading = page.locator("h1")
        expect(heading).to_have_text("Discogsography Dashboard")

    def test_service_cards_display(self, page: Page) -> None:
        """Test that service cards are displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for services section
        services_section = page.locator("section").filter(has_text="Services")
        expect(services_section).to_be_visible(timeout=10000)

        # Check for service cards - wait for them to be rendered
        service_cards = page.locator(".service-card")
        expect(service_cards).to_have_count(3, timeout=15000)

        # Check service names
        service_names = ["extractor", "graphinator", "tableinator"]
        for name in service_names:
            service = page.locator(".service-name", has_text=name)
            expect(service).to_be_visible()

    def test_queue_section_display(self, page: Page) -> None:
        """Test that queue section is displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for queues section
        queues_section = page.locator("section").filter(has_text="Message Queues")
        expect(queues_section).to_be_visible(timeout=10000)

        # Check for queue chart
        queue_chart = page.locator("#queueChart")
        expect(queue_chart).to_be_visible(timeout=10000)

    def test_database_cards_display(self, page: Page) -> None:
        """Test that database cards are displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for databases section
        databases_section = page.locator("section").filter(has_text="Databases")
        expect(databases_section).to_be_visible(timeout=10000)

        # Check for database cards
        database_cards = page.locator(".database-card")
        expect(database_cards).to_have_count(2, timeout=15000)

        # Check database names
        database_names = ["PostgreSQL", "Neo4j"]
        for name in database_names:
            database = page.locator(".database-name", has_text=name)
            expect(database).to_be_visible(timeout=10000)

    def test_websocket_connection(self, page: Page) -> None:
        """Test that WebSocket connection is established."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for connection status
        connection_status = page.locator(".connection-status")
        expect(connection_status).to_be_visible(timeout=10000)

        # Check that status shows connected
        status_text = page.locator(".status-text")
        expect(status_text).to_have_text("Connected", timeout=15000)

        # Check status indicator has connected class
        status_indicator = page.locator(".status-indicator")
        expect(status_indicator).to_have_class(re.compile(r"connected"), timeout=10000)

    def test_activity_log_display(self, page: Page) -> None:
        """Test that activity log is displayed."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for activity log section
        activity_section = page.locator("section").filter(has_text="Recent Activity")
        expect(activity_section).to_be_visible(timeout=10000)

        # Check for activity log
        activity_log = page.locator("#activityLog")
        expect(activity_log).to_be_visible(timeout=10000)

        # Should have at least one log entry (connection message)
        log_entries = page.locator(".log-entry")
        expect(log_entries.first).to_be_visible(timeout=15000)

    def test_responsive_design(self, page: Page) -> None:
        """Test that dashboard is responsive."""
        dashboard_url = "http://localhost:8003"
        page.goto(dashboard_url, wait_until="domcontentloaded")

        # Test desktop view
        page.set_viewport_size({"width": 1200, "height": 800})
        expect(page.locator(".container")).to_be_visible(timeout=10000)

        # Test mobile view
        page.set_viewport_size({"width": 375, "height": 667})
        expect(page.locator(".container")).to_be_visible(timeout=10000)

        # Check that grid layouts adjust
        queues_container = page.locator(".queues-container")
        expect(queues_container).to_be_visible(timeout=10000)

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
