# Test Coverage Improvement Plan

## Current Status

### Coverage Progress

- **Starting Coverage**: 19.6%
- **Current Coverage**: 38% ✅
- **Target Coverage**: >80%
- **Progress**: +18.4 percentage points

### Recent Achievements

1. ✅ Installed Playwright browsers for E2E testing
2. ✅ Fixed async test issues in `test_file_completion.py`
3. ✅ Created comprehensive tests for `common/neo4j_resilient.py` (18.4% → 98%)
4. ✅ Identified all modules with low/zero coverage
5. ✅ Validated quality checks (ruff, mypy) - only minor issues

## Coverage Breakdown by Module

### High Priority (Largest Impact)

| Module                               | Coverage | Statements | Missing | Priority |
| ------------------------------------ | -------- | ---------- | ------- | -------- |
| extractor/pyextractor/extractor.py   | 11%      | 571        | 508     | 🔴 HIGH  |
| graphinator/graphinator.py           | 48%      | 673        | 353     | 🟡 MED   |
| tableinator/tableinator.py           | 63%      | 388        | 143     | 🟢 LOW   |
| common/postgres_resilient.py         | 14%      | 173        | 149     | 🔴 HIGH  |
| common/rabbitmq_resilient.py         | 17%      | 154        | 128     | 🔴 HIGH  |
| common/db_resilience.py              | 36%      | 214        | 137     | 🟡 MED   |
| dashboard/dashboard.py               | 27%      | 379        | 277     | 🟡 MED   |
| discovery/api_realtime.py            | 33%      | 113        | 76      | 🟡 MED   |
| discovery/fulltext_search.py         | 21%      | 147        | 116     | 🟡 MED   |
| extractor/pyextractor/discogs.py     | 68%      | 207        | 66      | 🟢 LOW   |

### Already Excellent (>90%)

- ✅ common/neo4j_resilient.py: 98%
- ✅ discovery/analytics.py: 98%
- ✅ discovery/recommender.py: 98%
- ✅ discovery/validation.py: 100%
- ✅ discovery/metrics.py: 100%
- ✅ discovery/db_metrics.py: 100%

### Zero Coverage Discovery Modules (Defer to Phase 2)

These have 0% coverage but are less critical for MVP:

- discovery/ab_testing.py
- discovery/cache_invalidation.py
- discovery/centrality_metrics.py
- discovery/collaboration.py
- discovery/collaborative_filtering.py
- discovery/community_detection.py
- discovery/content_based.py
- discovery/explainability.py
- discovery/faceted_search.py
- discovery/genre_evolution.py
- discovery/hybrid_recommender.py
- discovery/semantic_search.py
- discovery/similarity_network.py
- discovery/trend_tracking.py
- discovery/websocket_manager.py

## Systematic Test Strategy

### Phase 1: Foundation Infrastructure (COMPLETED ✅)

**Goal**: Test core resilience and connection management

- [x] common/neo4j_resilient.py → 98% ✅
- [ ] common/postgres_resilient.py → Target: 80%+
- [ ] common/rabbitmq_resilient.py → Target: 80%+
- [ ] common/db_resilience.py → Target: 80%+

**Template**: Follow `tests/common/test_neo4j_resilient.py` pattern

### Phase 2: Core Services (IN PROGRESS)

**Goal**: Get main data processing services to 75%+

#### 2.1 Extractor Service

**File**: tests/extractor/test_extractor.py (augment existing)
**Current**: 11% → **Target**: 70%+

**Critical Functions to Test**:

```python
# High-value test targets in extractor.py:
- extract_artists()      # Core artist extraction
- extract_labels()       # Core label extraction
- extract_masters()      # Core master extraction
- extract_releases()     # Core release extraction
- main()                 # Main entry point
- setup_rabbitmq()       # Connection setup
- publish_message()      # Message publishing
- check_shutdown()       # Graceful shutdown
```

**Test Pattern**:

```python
"""Additional tests for extractor service."""
import pytest
from unittest.mock import Mock, patch, AsyncMock

class TestExtractArtists:
    """Test artist extraction functionality."""

    @pytest.fixture
    def mock_xml_data(self):
        """Mock XML data for testing."""
        return """
        <artists>
            <artist><id>1</id><name>Test Artist</name></artist>
        </artists>
        """

    @patch('extractor.extractor.get_channel')
    @patch('extractor.extractor.xmltodict.parse')
    def test_extract_artists_success(self, mock_parse, mock_channel):
        """Test successful artist extraction."""
        # Setup mocks
        mock_channel.return_value = Mock()
        mock_parse.return_value = {'artists': {'artist': [...]}}

        # Call function
        result = extract_artists('/path/to/artists.xml', mock_channel)

        # Assertions
        assert mock_parse.called
        assert mock_channel.called
```

#### 2.2 Graphinator Service

**File**: tests/graphinator/test_graphinator.py (augment existing)
**Current**: 48% → **Target**: 75%+

**Critical Functions to Test**:

```python
# High-value test targets in graphinator.py:
- on_artist_message()    # Message handler
- on_label_message()     # Message handler
- on_master_message()    # Message handler
- on_release_message()   # Message handler
- create_relationships() # Graph operations
- check_file_completion() # Already tested in test_file_completion.py
- main()                 # Main entry point
```

#### 2.3 Tableinator Service

**File**: tests/tableinator/test_tableinator.py (augment existing)
**Current**: 63% → **Target**: 80%+

**Critical Functions to Test**:

```python
# High-value test targets in tableinator.py:
- on_data_message()      # Message handler
- setup_database()       # DB initialization
- get_connection()       # Connection management
- create_tables()        # Schema creation
```

### Phase 3: Common Module Completion

Follow the same pattern as `test_neo4j_resilient.py`:

1. **test_postgres_resilient.py** - Test ResilientPostgresConnection class
2. **test_rabbitmq_resilient.py** - Test ResilientRabbitMQConnection class
3. **test_db_resilience.py** - Test base CircuitBreaker and ExponentialBackoff

**Template Structure**:

```python
"""Tests for <module> resilient connection."""
import pytest
from unittest.mock import Mock, patch, AsyncMock

class TestResilientConnection:
    """Test resilient connection class."""

    def test_init(self):
        """Test initialization."""
        pass

    def test_connection_creation(self):
        """Test connection creation."""
        pass

    def test_connection_health_check(self):
        """Test health check."""
        pass

    def test_retry_logic(self):
        """Test retry on failure."""
        pass

    def test_circuit_breaker(self):
        """Test circuit breaker activation."""
        pass

    def test_connection_cleanup(self):
        """Test connection cleanup."""
        pass
```

### Phase 4: Discovery Module Enhancement (Optional)

Only after reaching 80% overall coverage, add tests for:

- discovery/fulltext_search.py
- discovery/api_realtime.py
- Select modules from 0% coverage list

## Test Writing Guidelines

### 1. Unit Test Best Practices

```python
# ✅ Good: Focused, isolated, fast
def test_extract_artist_id():
    """Test extracting artist ID from XML."""
    data = {"artist": {"id": "123"}}
    result = extract_artist_id(data)
    assert result == "123"

# ❌ Bad: Too broad, slow, fragile
def test_entire_extraction_pipeline():
    """Test everything at once."""
    # Tests multiple services, databases, message queues
    # Fails for unclear reasons
```

### 2. Mocking Strategy

```python
# ✅ Mock external dependencies
@patch('module.external_api')
@patch('module.database_connection')
def test_with_mocks(mock_db, mock_api):
    """Test with mocked externals."""
    pass

# ❌ Don't mock the code under test
@patch('module.function_being_tested')  # Wrong!
def test_mocked_function(mock_func):
    """This doesn't test anything."""
    pass
```

### 3. Async Test Patterns

```python
# ✅ Proper async test
@pytest.mark.asyncio
async def test_async_function():
    """Test async functionality."""
    mock = AsyncMock(return_value="result")
    result = await async_function(mock)
    assert result == "result"

# ✅ Mock async dependencies
@patch('module.async_dependency')
async def test_with_async_mock(mock_dep):
    """Test with async mock."""
    mock_dep.return_value = AsyncMock(...)
```

### 4. Fixture Usage

```python
# ✅ Reusable fixtures
@pytest.fixture
def mock_config():
    """Provide test configuration."""
    return {"db_host": "localhost", "db_port": 5432}

@pytest.fixture
def mock_connection(mock_config):
    """Provide mock database connection."""
    conn = Mock()
    conn.execute = Mock(return_value=[])
    return conn
```

## Running Tests

### Run All Tests with Coverage

```bash
# Full test suite with coverage report
PYTHONPATH=. uv run pytest --cov=. --cov-report=term --cov-report=json -v

# Exclude E2E tests (faster)
PYTHONPATH=. uv run pytest -m "not e2e" --cov=. --cov-report=term --cov-report=json -v

# Run specific module tests
PYTHONPATH=. uv run pytest tests/common/test_neo4j_resilient.py -v

# Run with coverage for specific module
PYTHONPATH=. uv run pytest tests/common/ --cov=common --cov-report=term-missing -v
```

### Check Coverage Reports

```bash
# View JSON coverage data
python3 -c "import json; data=json.load(open('coverage.json')); print(f\"Overall: {data['totals']['percent_covered']:.1f}%\")"

# Generate HTML coverage report
uv run pytest --cov=. --cov-report=html
open htmlcov/index.html
```

## Quality Checks

### Run All Quality Checks

```bash
# Type checking
uv run mypy common/ dashboard/ discovery/ extractor/ graphinator/ tableinator/

# Linting
uv run ruff check .

# Format checking
uv run ruff format --check .

# Security scanning
uv run bandit -r common/ dashboard/ discovery/ extractor/ graphinator/ tableinator/
```

### Fix Common Issues

```bash
# Auto-fix linting issues
uv run ruff check --fix .

# Auto-format code
uv run ruff format .
```

## Next Steps

### Immediate Actions (To Reach 80%)

1. **Add Common Module Tests** (Est: +10-15% coverage)
   - Create `tests/common/test_postgres_resilient.py`
   - Create `tests/common/test_rabbitmq_resilient.py`
   - Create `tests/common/test_db_resilience.py`
   - Follow `test_neo4j_resilient.py` pattern

2. **Augment Extractor Tests** (Est: +15-20% coverage)
   - Add tests for core extraction functions
   - Mock XML parsing and RabbitMQ operations
   - Test error handling and edge cases

3. **Augment Graphinator Tests** (Est: +10-15% coverage)
   - Add tests for missing message handlers
   - Test relationship creation logic
   - Test Neo4j operations

4. **Augment Tableinator Tests** (Est: +5-10% coverage)
   - Add tests for database operations
   - Test table creation and migrations
   - Test connection management

### Estimated Coverage After Completion

- Common modules: 36% → 85% (Δ +49%)
- Extractor: 11% → 70% (Δ +59%)
- Graphinator: 48% → 75% (Δ +27%)
- Tableinator: 63% → 80% (Δ +17%)

**Projected Overall Coverage**: 80-85% ✅

## Success Criteria

- [ ] Overall test coverage >80%
- [ ] All critical paths in core services tested
- [ ] All resilient connection modules >80% coverage
- [ ] All tests passing without errors
- [ ] Quality checks (mypy, ruff) passing
- [ ] No failing E2E tests

## Resources

### Documentation

- [Pytest Documentation](https://docs.pytest.org/)
- [unittest.mock Guide](https://docs.python.org/3/library/unittest.mock.html)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov](https://pytest-cov.readthedocs.io/)

### Internal References

- Existing test patterns: `tests/common/test_neo4j_resilient.py`
- Service tests: `tests/extractor/`, `tests/graphinator/`, `tests/tableinator/`
- Discovery tests: `tests/discovery/`
- Project guidelines: `docs/CLAUDE.md`
- Emoji conventions: `docs/emoji-guide.md`
