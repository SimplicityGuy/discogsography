# Async Testing Lessons Learned

## The Bug That Wasn't Caught

### What Happened

A critical bug existed in `graphinator/batch_processor.py` where async Neo4j driver methods were being called with synchronous patterns:

```python
# WRONG - This was the bug
with self.driver.session(database="neo4j") as session:
    result = session.run(query, params)
    for record in result:
        # process record
```

This should have been:

```python
# CORRECT - Async patterns
async with await self.driver.session(database="neo4j") as session:
    result = await session.run(query, params)
    async for record in result:
        # process record
```

The error was: `'coroutine' object does not support the context manager protocol`

### Why Tests Didn't Catch It

The bug wasn't caught because of three testing antipatterns:

#### 1. **Batch Mode Was Disabled in Tests**

File: `tests/graphinator/conftest.py`

```python
@pytest.fixture(autouse=True)
def disable_batch_mode():
    """Disable batch mode for all graphinator tests."""
    with patch("graphinator.graphinator.BATCH_MODE", False):
        yield
```

**Impact**: The batch processor code was never executed during the test suite, so the bug remained hidden.

**Lesson**: Don't disable code paths in tests. If code is complex to test, write better integration tests.

#### 2. **Mocks Didn't Reflect Async Reality**

Original test mocks:

```python
mock_driver = MagicMock()
mock_session = MagicMock()
mock_driver.session.return_value.__enter__.return_value = mock_session
```

**Problem**: This mock works with synchronous `with` statements but doesn't enforce async patterns.

**What Should Have Been Used**:

```python
mock_session_context = AsyncMock()
mock_session_context.__aenter__.return_value = mock_session
mock_driver.session = AsyncMock(return_value=mock_session_context)
```

**Lesson**: Mocks should accurately represent the real behavior they're replacing, especially for async code.

#### 3. **No Integration Tests**

The codebase had:
- ❌ No integration tests with real async drivers
- ❌ No E2E tests that exercise batch processing
- ❌ No tests that verify async patterns are used correctly

**Lesson**: Unit tests with mocks are insufficient for async code. You need integration tests that verify async patterns work end-to-end.

## Prevention Strategies

### 1. Test Code Paths You Ship

**Rule**: If code exists in production, it must be tested.

**Implementation**:
- ✅ Create separate test files for batch mode (`test_batch_processor_integration.py`)
- ✅ Use parameterized tests to test both batch and non-batch modes
- ✅ Add coverage tracking to ensure all code paths are tested

**Example**:

```python
@pytest.mark.parametrize("batch_mode", [True, False])
def test_message_processing(batch_mode):
    with patch("graphinator.graphinator.BATCH_MODE", batch_mode):
        # Test both code paths
        ...
```

### 2. Use Realistic Mocks for Async Code

**Rule**: Async mocks must match the async/await patterns of the real code.

**Good Async Mock Pattern**:

```python
def create_async_session_mock():
    """Create realistic async driver mock."""
    mock_session = MagicMock()

    # Async context manager
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_session
    mock_context.__aexit__.return_value = None

    # Async method that returns context manager
    mock_driver = MagicMock()
    mock_driver.session = AsyncMock(return_value=mock_context)

    return mock_driver, mock_session
```

**Use Shared Fixtures**: The project has a proper `mock_neo4j_driver` fixture in `tests/conftest.py` that should be reused.

### 3. Add Integration Tests for Async Code

**Rule**: Critical async code paths must have integration tests that verify async patterns.

**What to Test**:

✅ **Context Manager Behavior**
```python
@pytest.mark.asyncio
async def test_session_is_async_context_manager():
    """Verify async with await pattern works."""
    async with await driver.session() as session:
        # Should not raise TypeError
        pass
```

✅ **Async Method Calls**
```python
@pytest.mark.asyncio
async def test_methods_are_awaited():
    """Verify methods are called with await."""
    result = await session.run(query)  # Must be awaited
```

✅ **Async Iteration**
```python
@pytest.mark.asyncio
async def test_async_iteration():
    """Verify async for is used."""
    async for record in result:  # Must be async for
        process(record)
```

### 4. Use Type Checking to Catch Async Mismatches

**Enable Strict Async Checking in mypy**:

```toml
[tool.mypy]
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
check_untyped_defs = true
```

**Type Hints Help Catch Errors**:

```python
async def process_batch(
    self,
    messages: list[PendingMessage]
) -> None:  # Return type enforces this is async
    # mypy will catch if we forget await
    session = await self.driver.session()  # Type: AsyncSession
```

### 5. Add Pre-commit Hooks for Async Patterns

**Create a simple checker**:

```python
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: check-async-patterns
      name: Check async/await patterns
      entry: python scripts/check_async.py
      language: python
      files: \.py$
```

**Script to catch common mistakes**:

```python
# scripts/check_async.py
import re
import sys

async_driver_pattern = r'with\s+.*driver\.session\('

for line in sys.stdin:
    if re.search(async_driver_pattern, line):
        print(f"ERROR: Found 'with driver.session()' - should be 'async with await'")
        sys.exit(1)
```

## Testing Checklist for Async Code

When adding or modifying async code:

- [ ] Verify async methods are marked with `async def`
- [ ] Verify all async calls use `await`
- [ ] Verify context managers use `async with await`
- [ ] Verify iterations use `async for`
- [ ] Add unit tests with realistic async mocks
- [ ] Add integration tests that exercise real async patterns
- [ ] Run mypy with strict async checking
- [ ] Verify code coverage includes the async code paths
- [ ] Test error conditions (exceptions in async context)
- [ ] Test cleanup behavior (context manager __aexit__)

## Example: Good Test Structure

```python
class TestAsyncFeature:
    """Test async feature with proper patterns."""

    @pytest.fixture
    def async_driver(self):
        """Use the shared realistic async mock."""
        return create_async_session_mock()

    @pytest.mark.asyncio
    async def test_happy_path(self, async_driver):
        """Test normal operation."""
        mock_driver, mock_session = async_driver

        # Configure behavior
        mock_session.run = AsyncMock(return_value=mock_result)

        # Exercise code
        await my_async_function(mock_driver)

        # Verify async patterns were used
        mock_driver.session.assert_called()  # Session was requested
        mock_session.run.assert_called()     # Query was run

    @pytest.mark.asyncio
    async def test_error_handling(self, async_driver):
        """Test error conditions."""
        mock_driver, mock_session = async_driver

        # Configure error
        mock_session.run = AsyncMock(side_effect=Exception("Test error"))

        # Should handle gracefully
        await my_async_function(mock_driver)

        # Verify cleanup happened
        context = await mock_driver.session()
        context.__aexit__.assert_called()
```

## References

- [Python Async/Await Testing Best Practices](https://docs.python.org/3/library/unittest.mock.html#unittest.mock.AsyncMock)
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
- [Neo4j Python Driver Async API](https://neo4j.com/docs/api/python-driver/current/async_api.html)

## Action Items

1. ✅ Add integration tests for batch processor async patterns
2. ⬜ Enable batch mode in a subset of existing tests
3. ⬜ Add mypy strict async checking to CI/CD
4. ⬜ Create shared async driver fixtures for all services
5. ⬜ Add pre-commit hook for async pattern checking
6. ⬜ Document async testing standards in CONTRIBUTING.md
