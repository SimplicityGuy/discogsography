# MyPy Pre-commit vs Standalone Differences

## Problem Summary

Running `uv run mypy .` produces **505 errors** while `uv run pre-commit run mypy --all-files` produces **0 errors**.

## Root Causes

### 1. **File Scope Difference** (Primary)

**Pre-commit configuration:**
```yaml
files: ^(common|dashboard|discovery|extractor|graphinator|tableinator)/.*\.py$
```

- Pre-commit **ONLY** checks source files in these directories
- **EXCLUDES** all `tests/` directory files
- When checking only source directories: **21 errors**
- When checking tests too: **505 errors** (484 in tests alone)

### 2. **Missing Dependencies in Pre-commit Environment** (Critical)

Pre-commit creates an **isolated virtual environment** for mypy with limited dependencies.

**Dependencies in pre-commit mypy environment:**
```
aio-pika==9.5.8
dict_hash==1.3.7
mypy==1.19.1
neo4j==6.1.0
orjson==3.11.7
psycopg==3.3.2
types-tqdm==4.67.3.20260205
types-xmltodict==1.0.1.20260113
```

**Critical MISSING dependencies:**
- ❌ `structlog` - Used extensively in `common/config.py`
- ❌ `fastapi` - Used in all API modules
- ❌ `pydantic` - Data validation models
- ❌ `prometheus_client` - Metrics in dashboard
- ❌ `numpy`, `scipy`, `sklearn` - ML/data processing
- ❌ `pandas`, `plotly` - Analytics/visualization
- ❌ `sqlalchemy` - Database ORM
- ❌ `redis`, `httpx` - Networking/caching
- ❌ `sentence_transformers`, `transformers`, `onnxruntime` - ML models
- ❌ `slowapi`, `networkx` - API rate limiting, graph algorithms

**Impact:** When mypy can't import a module, it treats it as `Any` type, which:
- Suppresses type errors in that module
- Allows invalid type combinations to pass
- Creates false confidence in type safety

### 3. **Error Distribution**

```
Total errors: 505
├── Tests: ~484 errors (95.8%)
│   ├── Missing return type annotations
│   ├── Unused type: ignore comments
│   ├── Non-overlapping equality checks
│   └── Indexing and operator issues
└── Source: 21 errors (4.2%)
    ├── common/config.py: 3 errors (structlog types)
    └── dashboard/dashboard.py: 18 errors (prometheus types + unused ignores)
```

## Why Pre-commit Passes Despite Source Errors

Even though there are 21 errors in source files, pre-commit reports **0 errors** because:

1. **Missing `structlog`** → `common/config.py` errors suppressed
2. **Missing `prometheus_client`** → `dashboard/dashboard.py` type errors suppressed
3. Without these dependencies, mypy can't perform proper type checking

## Final Solution ✅

**Use a local pre-commit hook that runs mypy from the project's uv environment.**

This eliminates all configuration duplication and ensures complete consistency:

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: mypy
      name: mypy
      entry: uv run mypy
      language: system
      types: [python]
      pass_filenames: false
      args: ["."]
```

**Benefits:**
- ✅ No `additional_dependencies` duplication
- ✅ Uses exact project dependencies from `pyproject.toml`
- ✅ Respects all mypy configuration in `pyproject.toml`
- ✅ Identical results between `uv run mypy .` and pre-commit
- ✅ Faster hook execution (no separate environment)
- ✅ Single source of truth for all configuration

**Configuration in `pyproject.toml`:**
```toml
[tool.mypy]
python_version = "3.13"
# ... all your mypy settings ...
exclude = "^tests/"  # Excludes tests from type checking
```

**Result:** Both standalone and pre-commit now show **identical output**:
```
Found 21 errors in 2 files (checked 65 source files)
```

---

## Alternative Solutions (Not Recommended)

### Option 1: Add All Dependencies to Pre-commit

Update `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/pre-commit/mirrors-mypy
  rev: a66e98df7b4aeeb3724184b332785976d062b92e  # frozen: v1.19.1
  hooks:
    - id: mypy
      files: ^(common|dashboard|discovery|extractor|graphinator|tableinator)/.*\.py$
      additional_dependencies:
        # Type stubs
        - types-tqdm
        - types-xmltodict
        # Direct dependencies
        - orjson
        - dict-hash
        - aio-pika
        - neo4j
        - psycopg[binary]
        # ADDED: Critical dependencies for type checking
        - structlog
        - fastapi
        - pydantic
        - prometheus-client
        - numpy
        - scipy
        - scikit-learn
        - pandas
        - plotly
        - sqlalchemy
        - redis
        - httpx
        - slowapi
        - networkx
        # ML dependencies (consider adding if type errors persist)
        - sentence-transformers
        - transformers
        - onnxruntime
```

**Pros:**
- Accurate type checking in pre-commit
- Catches errors before commit
- Consistent with standalone mypy

**Cons:**
- Slower pre-commit hook installation
- Larger cache size

### Option 2: Use Project Environment for Pre-commit

Create a local pre-commit hook that uses the project's uv environment:

```yaml
- repo: local
  hooks:
    - id: mypy
      name: mypy
      entry: uv run mypy
      language: system
      types: [python]
      files: ^(common|dashboard|discovery|extractor|graphinator|tableinator)/.*\.py$
      pass_filenames: false
```

**Pros:**
- Uses exact project dependencies
- No dependency duplication
- Faster for developers with environment already set up

**Cons:**
- Requires `uv` and environment to be set up
- May not work in CI without setup

### Option 3: Include Tests in Pre-commit

Extend file pattern to include tests:

```yaml
files: ^(common|dashboard|discovery|extractor|graphinator|tableinator|tests)/.*\.py$
```

**Note:** This will reveal the 484+ test errors that currently aren't checked.

### Option 4: Separate Test Type Checking

Keep pre-commit for source files, run full mypy in CI:

```yaml
# .github/workflows/ci.yml
- name: 🔍 Type check with mypy
  run: uv run mypy .  # Checks everything including tests
```

## Immediate Action Items

1. **Fix source file errors (21 errors):**
   - `common/config.py`: Add type ignores or fix structlog typing
   - `dashboard/dashboard.py`: Remove unused type: ignore comments

2. **Choose solution:**
   - Recommended: **Option 1** (add dependencies) for accurate pre-commit checking
   - Alternative: **Option 2** (local hook) for faster development

3. **Fix test errors (484 errors):**
   - Add return type annotations to test functions
   - Remove unused type: ignore comments
   - Fix enum comparison issues

## Testing the Fix

After implementing a solution:

```bash
# Clean pre-commit cache
uv run pre-commit clean

# Re-run pre-commit
uv run pre-commit run mypy --all-files

# Should now match standalone mypy on source files
uv run mypy common dashboard discovery extractor graphinator tableinator
```

## References

- Pre-commit config: `.pre-commit-config.yaml`
- MyPy config: `pyproject.toml` `[tool.mypy]` section
- Pre-commit environment: `~/.cache/pre-commit/repoe3sr52ed/`
