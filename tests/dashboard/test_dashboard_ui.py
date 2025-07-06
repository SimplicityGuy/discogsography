"""Playwright tests for the dashboard UI."""
# mypy: disable-error-code="no-untyped-def"

import re

import pytest
from playwright.async_api import Page, expect


@pytest.mark.e2e
class TestDashboardUI:
    """Test the dashboard user interface.

    Note: These tests require the dashboard to be running on http://localhost:8003.
    Use scripts/test-e2e.sh to run these tests with proper setup.

    To run these tests:
    1. Start the dashboard: uv run python dashboard/dashboard.py
    2. Run tests: uv run pytest tests/dashboard/test_dashboard_ui.py -m e2e

    Or use the convenience script: ./scripts/test-e2e.sh
    """

    @pytest.mark.asyncio
    async def test_dashboard_loads(self, page: Page) -> None:
        """Test that the dashboard page loads successfully."""
        # This test assumes the dashboard is running at http://localhost:8003
        # In CI, this would be started by docker-compose or a test fixture
        dashboard_url = "http://localhost:8003"

        # Navigate to the dashboard
        await page.goto(dashboard_url, wait_until="domcontentloaded", timeout=10000)

        # Check page title
        await expect(page).to_have_title("Discogsography Dashboard")

        # Check main heading
        heading = page.locator("h1")
        await expect(heading).to_have_text("Discogsography Dashboard")

    @pytest.mark.asyncio
    async def test_service_cards_display(self, page: Page) -> None:
        """Test that service cards are displayed."""
        dashboard_url = "http://localhost:8003"
        await page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for services section
        services_section = page.locator("section").filter(has_text="Services")
        await expect(services_section).to_be_visible(timeout=10000)

        # Check for service cards - wait for them to be rendered
        service_cards = page.locator(".service-card")
        await expect(service_cards).to_have_count(3, timeout=15000)

        # Check service names
        service_names = ["extractor", "graphinator", "tableinator"]
        for name in service_names:
            service = page.locator(".service-name", has_text=name)
            await expect(service).to_be_visible()

    @pytest.mark.asyncio
    async def test_queue_section_display(self, page: Page) -> None:
        """Test that queue section is displayed."""
        dashboard_url = "http://localhost:8003"
        await page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for queues section
        queues_section = page.locator("section").filter(has_text="Message Queues")
        await expect(queues_section).to_be_visible(timeout=10000)

        # Check for queue chart
        queue_chart = page.locator("#queueChart")
        await expect(queue_chart).to_be_visible(timeout=10000)

    @pytest.mark.asyncio
    async def test_database_cards_display(self, page: Page) -> None:
        """Test that database cards are displayed."""
        dashboard_url = "http://localhost:8003"
        await page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for databases section
        databases_section = page.locator("section").filter(has_text="Databases")
        await expect(databases_section).to_be_visible(timeout=10000)

        # Check for database cards
        database_cards = page.locator(".database-card")
        await expect(database_cards).to_have_count(2, timeout=15000)

        # Check database names
        database_names = ["PostgreSQL", "Neo4j"]
        for name in database_names:
            database = page.locator(".database-name", has_text=name)
            await expect(database).to_be_visible(timeout=10000)

    @pytest.mark.asyncio
    async def test_websocket_connection(self, page: Page) -> None:
        """Test that WebSocket connection is established."""
        dashboard_url = "http://localhost:8003"
        await page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for connection status
        connection_status = page.locator(".connection-status")
        await expect(connection_status).to_be_visible(timeout=10000)

        # Check that status shows connected
        status_text = page.locator(".status-text")
        await expect(status_text).to_have_text("Connected", timeout=15000)

        # Check status indicator has connected class
        status_indicator = page.locator(".status-indicator")
        await expect(status_indicator).to_have_class(re.compile(r"connected"), timeout=10000)

    @pytest.mark.asyncio
    async def test_activity_log_display(self, page: Page) -> None:
        """Test that activity log is displayed."""
        dashboard_url = "http://localhost:8003"
        await page.goto(dashboard_url, wait_until="domcontentloaded")

        # Wait for activity log section
        activity_section = page.locator("section").filter(has_text="Recent Activity")
        await expect(activity_section).to_be_visible(timeout=10000)

        # Check for activity log
        activity_log = page.locator("#activityLog")
        await expect(activity_log).to_be_visible(timeout=10000)

        # Should have at least one log entry (connection message)
        log_entries = page.locator(".log-entry")
        await expect(log_entries.first()).to_be_visible(timeout=15000)

    @pytest.mark.asyncio
    async def test_responsive_design(self, page: Page) -> None:
        """Test that dashboard is responsive."""
        dashboard_url = "http://localhost:8003"
        await page.goto(dashboard_url, wait_until="domcontentloaded")

        # Test desktop view
        await page.set_viewport_size({"width": 1200, "height": 800})
        await expect(page.locator(".container")).to_be_visible(timeout=10000)

        # Test mobile view
        await page.set_viewport_size({"width": 375, "height": 667})
        await expect(page.locator(".container")).to_be_visible(timeout=10000)

        # Check that grid layouts adjust
        queues_container = page.locator(".queues-container")
        await expect(queues_container).to_be_visible(timeout=10000)

    @pytest.mark.asyncio
    async def test_api_endpoints(self, page: Page) -> None:
        """Test that API endpoints are accessible."""
        dashboard_url = "http://localhost:8003"

        # Test metrics endpoint
        response = await page.request.get(f"{dashboard_url}/api/metrics")
        assert response.ok
        data = await response.json()
        assert "services" in data
        assert "queues" in data
        assert "databases" in data

        # Test services endpoint
        response = await page.request.get(f"{dashboard_url}/api/services")
        assert response.ok
        services = await response.json()
        assert isinstance(services, list)

        # Test queues endpoint
        response = await page.request.get(f"{dashboard_url}/api/queues")
        assert response.ok
        queues = await response.json()
        assert isinstance(queues, list)

        # Test databases endpoint
        response = await page.request.get(f"{dashboard_url}/api/databases")
        assert response.ok
        databases = await response.json()
        assert isinstance(databases, list)
