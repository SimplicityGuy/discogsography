# 🧪 Testing Guide

> Comprehensive testing strategies for the Discogsography monorepo

## Overview

Discogsography employs a multi-layered testing approach including unit tests, integration tests, and end-to-end (E2E) tests. This guide covers testing patterns, best practices, and common scenarios.

## 🎯 Testing Philosophy

### Testing Pyramid

```
         /\        E2E Tests (Playwright)
        /  \       - User workflows
       /    \      - Browser testing
      /      \
     /--------\    Integration Tests
    /          \   - Service interactions
   /            \  - Database operations
  /              \
 /________________\ Unit Tests
                    - Business logic
                    - Individual functions
```

### Coverage Goals

| Test Type | Target Coverage | Current Focus |
|-----------|----------------|---------------|
| Unit Tests | 80%+ | Core business logic |
| Integration | 70%+ | Service boundaries |
| E2E Tests | Critical paths | User workflows |

## 🛠️ Test Structure

```
tests/
├── conftest.py                    # Shared fixtures
├── test_config.py                 # Configuration tests
├── test_integration.py            # Cross-service tests
│
├── dashboard/
│   ├── conftest.py               # Dashboard fixtures
│   ├── test_dashboard_api.py     # API unit tests
│   ├── test_dashboard_api_integration.py
│   └── test_dashboard_ui.py      # E2E tests
│
├── discovery/
│   ├── test_discovery.py         # Service tests
│   ├── test_recommender.py       # AI component tests
│   ├── test_analytics.py         # Analytics tests
│   └── test_graph_explorer.py    # Graph tests
│
├── extractor/
│   ├── test_extractor.py         # Processing tests
│   └── test_discogs.py           # Download tests
│
├── graphinator/
│   └── test_graphinator.py       # Neo4j tests
│
└── tableinator/
    └── test_tableinator.py       # PostgreSQL tests
```

## 📝 Writing Tests

### Unit Test Pattern

```python
import pytest
from unittest.mock import AsyncMock, patch


class TestArtistProcessor:
    """Test artist processing logic."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock database connection."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        return conn

    @pytest.mark.asyncio
    async def test_process_artist_success(self, mock_connection):
        """Test successful artist processing."""
        # Arrange
        artist_data = {"id": "123", "name": "Test Artist", "profile": "Test profile"}

        # Act
        result = await process_artist(artist_data, mock_connection)

        # Assert
        assert result["status"] == "success"
        mock_connection.execute.assert_called_once()
```

### Integration Test Pattern

```python
@pytest.mark.integration
class TestServiceIntegration:
    """Test service interactions."""

    @pytest.fixture
    async def services(self):
        """Start test services."""
        async with TestEnvironment() as env:
            yield env

    @pytest.mark.asyncio
    async def test_message_flow(self, services):
        """Test message flow between services."""
        # Send test message
        await services.publish_message("test_queue", {"test": "data"})

        # Verify processing
        result = await services.wait_for_result(timeout=5)
        assert result["processed"] is True
```

### E2E Test Pattern

```python
@pytest.mark.e2e
class TestDashboardUI:
    """Test dashboard user interface."""

    @pytest.fixture
    async def dashboard_page(self, test_server, page):
        """Navigate to dashboard."""
        await page.goto(f"http://localhost:{test_server.port}")
        return page

    async def test_service_health_display(self, dashboard_page):
        """Test service health indicators."""
        # Wait for dashboard to load
        await dashboard_page.wait_for_selector(".service-health")

        # Check all services shown
        services = await dashboard_page.query_selector_all(".service-card")
        assert len(services) == 5

        # Verify health status
        health_status = await dashboard_page.text_content(".health-status")
        assert health_status in ["Healthy", "Starting"]
```

## 🔧 Test Fixtures

### Common Fixtures

```python
# tests/conftest.py
@pytest.fixture
def mock_amqp_connection():
    """Mock AMQP connection for testing."""
    connection = AsyncMock()
    channel = AsyncMock()

    connection.channel = AsyncMock(return_value=channel)
    channel.declare_queue = AsyncMock()
    channel.basic_consume = AsyncMock()

    return connection


@pytest.fixture
def test_config():
    """Test configuration."""
    return Config(
        amqp_connection="amqp://test@localhost",
        neo4j_address="bolt://localhost:7687",
        neo4j_username="test",
        neo4j_password="test",
        postgres_address="localhost:5432",
        postgres_username="test",
        postgres_password="test",
        postgres_database="test_db",
    )
```

### Service-Specific Fixtures

```python
# tests/dashboard/conftest.py
@pytest.fixture
async def test_server():
    """Start test dashboard server."""
    server = TestServer(port=0)  # Random port
    await server.start()

    yield server

    await server.stop()


@pytest.fixture
def test_client(test_server):
    """Create test client."""
    return TestClient(test_server.app)
```

## 🚀 Running Tests

### Quick Commands

```bash
# Run all tests (excluding E2E)
uv run task test

# Run with coverage
uv run task test-cov

# Run specific service tests
uv run pytest tests/dashboard/ -v
uv run pytest tests/extractor/ -v

# Run only unit tests
uv run pytest -m "not integration and not e2e"

# Run only integration tests
uv run pytest -m integration

# Run E2E tests
uv run task test-e2e
```

### Advanced Testing

```bash
# Run specific test
uv run pytest tests/test_config.py::test_config_validation -v

# Run with debugging
uv run pytest -xvs --tb=short

# Run parallel
uv run pytest -n auto

# Generate HTML coverage report
uv run pytest --cov --cov-report=html
open htmlcov/index.html
```

## 🎭 E2E Testing with Playwright

### Setup

```bash
# Install Playwright browsers
uv run playwright install chromium firefox webkit
uv run playwright install-deps

# Run E2E tests
uv run pytest -m e2e
```

### Writing E2E Tests

```python
import pytest
from playwright.async_api import Page


@pytest.mark.e2e
async def test_dashboard_navigation(page: Page, test_server):
    """Test dashboard navigation."""
    # Navigate to dashboard
    await page.goto(f"http://localhost:{test_server.port}")

    # Test navigation menu
    await page.click("button.menu-toggle")
    await page.wait_for_selector("nav.menu", state="visible")

    # Navigate to discovery
    await page.click("text=AI Discovery")
    await page.wait_for_url("**/discovery")

    # Verify page loaded
    assert await page.title() == "Music Discovery - Discogsography"
```

### Browser Configuration

```python
# Run on specific browser
pytest -m e2e --browser chromium
pytest -m e2e --browser firefox
pytest -m e2e --browser webkit

# Run with visible browser
pytest -m e2e --headed

# Run with slowmo for debugging
pytest -m e2e --headed --slowmo 1000

# Device emulation
pytest -m e2e --device "iPhone 13"
```

## 🧩 Mocking Strategies

### Database Mocking

```python
@pytest.fixture
def mock_neo4j():
    """Mock Neo4j driver."""
    driver = AsyncMock()
    session = AsyncMock()

    driver.session = MagicMock(return_value=session)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    session.run = AsyncMock()

    return driver


@pytest.fixture
def mock_postgres():
    """Mock PostgreSQL connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)

    return conn
```

### External Service Mocking

```python
@pytest.fixture
def mock_discogs_api(httpx_mock):
    """Mock Discogs API responses."""
    httpx_mock.add_response(
        url="https://api.discogs.com/database/search",
        json={"results": [{"id": 1, "title": "Test"}]},
    )
    return httpx_mock
```

## 📊 Test Organization

### Test Naming

```python
# Pattern: test_<what>_<condition>_<expected>
def test_config_validation_missing_field_raises_error():
    pass


def test_artist_processing_duplicate_skips_record():
    pass


def test_download_large_file_shows_progress():
    pass
```

### Test Classes

```python
class TestArtistProcessor:
    """Group related tests."""

    class TestValidation:
        """Validation-specific tests."""

        def test_valid_artist_passes(self):
            pass

        def test_missing_id_fails(self):
            pass

    class TestProcessing:
        """Processing-specific tests."""

        @pytest.mark.asyncio
        async def test_successful_processing(self):
            pass
```

## ⚠️ Common Pitfalls

### 1. Missing Async Markers

```python
# ❌ Wrong
async def test_async_operation():
    await some_async_call()


# ✅ Correct
@pytest.mark.asyncio
async def test_async_operation():
    await some_async_call()
```

### 2. Resource Cleanup

```python
# ❌ Wrong - No cleanup
def test_file_operation():
    create_test_file()
    # Test...


# ✅ Correct - With cleanup
def test_file_operation(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")
    # Test...
    # Cleanup handled by pytest
```

### 3. Test Isolation

```python
# ❌ Wrong - Shared state
class TestCounter:
    counter = 0

    def test_increment(self):
        self.counter += 1
        assert self.counter == 1  # Fails on second run


# ✅ Correct - Isolated state
class TestCounter:
    def test_increment(self):
        counter = 0
        counter += 1
        assert counter == 1
```

## 🎯 Best Practices

1. **Test One Thing**: Each test should verify a single behavior
1. **Use Descriptive Names**: Test names should explain what they test
1. **Arrange-Act-Assert**: Structure tests clearly
1. **Mock External Dependencies**: Don't make real network calls
1. **Use Fixtures**: Share setup code through fixtures
1. **Test Edge Cases**: Empty data, nulls, errors
1. **Keep Tests Fast**: Mock slow operations
1. **Test Public APIs**: Not implementation details

## 📈 Coverage Requirements

### Viewing Coverage

```bash
# Generate coverage report
uv run task test-cov

# View in terminal
coverage report

# Generate HTML report
coverage html
open htmlcov/index.html
```

### Coverage Configuration

```toml
# pyproject.toml
[tool.coverage.run]
source = ["dashboard", "discovery", "extractor", "graphinator", "tableinator", "common"]
omit = ["*/tests/*", "*/__pycache__/*", "*/static/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if __name__ == .__main__.:",
    "raise AssertionError",
    "raise NotImplementedError",
]
```

## 🔍 Debugging Tests

### Debugging Techniques

```bash
# Stop on first failure
uv run pytest -x

# Show print statements
uv run pytest -s

# Verbose output
uv run pytest -v

# Show local variables on failure
uv run pytest -l

# Drop into debugger on failure
uv run pytest --pdb
```

### VS Code Integration

```json
// .vscode/settings.json
{
    "python.testing.pytestEnabled": true,
    "python.testing.unittestEnabled": false,
    "python.testing.pytestArgs": [
        "--no-cov"  // Disable coverage in VS Code
    ]
}
```

## 📚 Additional Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)
- [Playwright Python](https://playwright.dev/python/)
- [Coverage.py](https://coverage.readthedocs.io/)
