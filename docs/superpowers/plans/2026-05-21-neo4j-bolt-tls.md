# Neo4j Bolt TLS Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in, secure-by-default TLS for the Neo4j Bolt connection across all services, controlled by two env vars and a single shared helper.

**Architecture:** A pure helper `neo4j_security_kwargs()` in `common/config.py` reads `NEO4J_TLS_ENABLED` / `NEO4J_TLS_VERIFY` and returns neo4j-driver security kwargs (`encrypted` + `trusted_certificates`). Every Neo4j driver construction site spreads `**neo4j_security_kwargs()` instead of hardcoding `encrypted=False`. The resilient driver already forwards `**driver_kwargs` to `GraphDatabase.driver` (proven by `tests/common/test_neo4j_resilient.py:62`), so no driver-class changes are needed.

**Tech Stack:** Python 3.13, `neo4j==6.2.0` (`TrustSystemCAs`/`TrustAll` from top-level `neo4j`), structlog, pytest, uv, just.

**Spec:** `docs/superpowers/specs/2026-05-21-neo4j-bolt-tls-design.md`

---

## File Structure

| File | Responsibility | Change |
| ---- | -------------- | ------ |
| `common/config.py` | Define `neo4j_security_kwargs()` | Modify |
| `common/__init__.py` | Re-export the helper | Modify |
| `tests/common/test_config.py` | Unit tests for the helper | Modify |
| `api/api.py` | Apply helper at driver site (~250) | Modify |
| `dashboard/dashboard.py` | Apply helper at driver site (~163) | Modify |
| `graphinator/graphinator.py` | Apply helper at driver site (~1345) | Modify |
| `brainzgraphinator/brainzgraphinator.py` | Apply helper at driver site (~904) | Modify |
| `schema-init/schema_init.py` | Apply helper at driver site (~128) | Modify |
| `tests/perftest/run_perftest.py` | Apply helper at raw driver site (~102) | Modify |
| `docs/configuration.md` | Document env vars + operator TLS guide | Modify |
| `CLAUDE.md` | Note the two new env vars | Modify |

---

## Task 1: `neo4j_security_kwargs()` helper (TDD)

**Files:**
- Modify: `common/config.py` (add helper after `_build_redis_url()`, before `class ExtractorConfig`)
- Modify: `common/__init__.py` (re-export)
- Test: `tests/common/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/common/test_config.py`. Note `import logging` is already at the top of the file; add `import structlog` near the existing imports if not present, and import the helper from `common`.

```python
class TestNeo4jSecurityKwargs:
    """Tests for neo4j_security_kwargs() TLS helper."""

    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NEO4J_TLS_ENABLED", raising=False)
        monkeypatch.delenv("NEO4J_TLS_VERIFY", raising=False)
        assert neo4j_security_kwargs() == {}

    def test_explicit_disabled_ignores_verify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEO4J_TLS_ENABLED", "false")
        monkeypatch.setenv("NEO4J_TLS_VERIFY", "false")
        assert neo4j_security_kwargs() == {}

    def test_enabled_verify_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from neo4j import TrustSystemCAs

        monkeypatch.setenv("NEO4J_TLS_ENABLED", "true")
        monkeypatch.delenv("NEO4J_TLS_VERIFY", raising=False)
        kwargs = neo4j_security_kwargs()
        assert kwargs["encrypted"] is True
        assert isinstance(kwargs["trusted_certificates"], TrustSystemCAs)

    def test_enabled_verify_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from neo4j import TrustSystemCAs

        monkeypatch.setenv("NEO4J_TLS_ENABLED", "true")
        monkeypatch.setenv("NEO4J_TLS_VERIFY", "true")
        kwargs = neo4j_security_kwargs()
        assert kwargs["encrypted"] is True
        assert isinstance(kwargs["trusted_certificates"], TrustSystemCAs)

    def test_enabled_no_verify_uses_trust_all_and_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from neo4j import TrustAll

        monkeypatch.setenv("NEO4J_TLS_ENABLED", "true")
        monkeypatch.setenv("NEO4J_TLS_VERIFY", "false")
        with structlog.testing.capture_logs() as logs:
            kwargs = neo4j_security_kwargs()
        assert kwargs["encrypted"] is True
        assert isinstance(kwargs["trusted_certificates"], TrustAll)
        assert any(entry.get("log_level") == "warning" for entry in logs)

    def test_enabled_accepts_case_and_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ["TRUE", "True", " true "]:
            monkeypatch.setenv("NEO4J_TLS_ENABLED", value)
            assert neo4j_security_kwargs() != {}

    def test_non_true_values_stay_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ["1", "yes", "on", ""]:
            monkeypatch.setenv("NEO4J_TLS_ENABLED", value)
            assert neo4j_security_kwargs() == {}
```

Add `neo4j_security_kwargs` to the existing `from common import (...)` import at the top of the test file (it currently imports `BrainzgraphinatorConfig, ... setup_logging`). Add `import structlog` if not already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/common/test_config.py::TestNeo4jSecurityKwargs -p no:cov -q`
Expected: FAIL — `ImportError: cannot import name 'neo4j_security_kwargs'`.

- [ ] **Step 3: Implement the helper in `common/config.py`**

Insert immediately after the `_build_redis_url()` function (around line 78) and before `@dataclass(frozen=True)\nclass ExtractorConfig:`. `getenv`, `Any`, and the module `logger` (structlog) are already imported at the top of the file.

```python
def neo4j_security_kwargs() -> dict[str, Any]:
    """Build neo4j driver TLS/security kwargs from NEO4J_TLS_* environment variables.

    Controls Bolt transport encryption for every service's Neo4j driver:

    - TLS disabled (default)      -> {}  (plaintext bolt://, unchanged behavior)
    - enabled, verify (default)   -> encrypted=True + TrustSystemCAs() (verify cert vs system CAs)
    - enabled, verify disabled    -> encrypted=True + TrustAll() (encrypted, identity unverified)

    Only a case-insensitive "true" enables each flag (project boolean convention).
    The neo4j TrustStore classes are imported lazily so non-graph services that import
    this module do not pay the neo4j import cost at module load.
    """
    if getenv("NEO4J_TLS_ENABLED", "false").strip().lower() != "true":
        return {}

    from neo4j import TrustAll, TrustSystemCAs

    if getenv("NEO4J_TLS_VERIFY", "true").strip().lower() == "true":
        logger.info("🛡️ Neo4j Bolt TLS enabled (encrypted, verifying server certificate)")
        return {"encrypted": True, "trusted_certificates": TrustSystemCAs()}

    logger.warning(
        "⚠️ Neo4j Bolt TLS enabled WITHOUT certificate verification — traffic is encrypted "
        "but the server identity is not verified (no MITM protection)"
    )
    return {"encrypted": True, "trusted_certificates": TrustAll()}
```

- [ ] **Step 4: Re-export from `common/__init__.py`**

In the `from common.config import (...)` block, add `neo4j_security_kwargs,` between `get_config,` and `setup_logging,` (keeping the lowercase-function ordering):

```python
    get_config,
    neo4j_security_kwargs,
    setup_logging,
```

In the `__all__` list, add `"neo4j_security_kwargs",` among the lowercase entries (e.g., directly after `"get_config",` if present, otherwise alongside the other function names):

```python
    "neo4j_security_kwargs",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/common/test_config.py::TestNeo4jSecurityKwargs -p no:cov -q`
Expected: PASS (7 tests).

- [ ] **Step 6: Lint the changed files**

Run: `uv run ruff format common/config.py common/__init__.py tests/common/test_config.py && uv run ruff check common/config.py common/__init__.py tests/common/test_config.py && uv run mypy common/config.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add common/config.py common/__init__.py tests/common/test_config.py
git commit -m "feat(common): add neo4j_security_kwargs() Bolt TLS helper

Reads NEO4J_TLS_ENABLED / NEO4J_TLS_VERIFY and returns neo4j driver
security kwargs (encrypted + trusted_certificates). Default off; secure
(verify) by default when enabled. Resolves the client side of #74.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Apply helper at the four resilient-driver service sites

**Files:**
- Modify: `api/api.py` (import line 73; constructor ~250)
- Modify: `dashboard/dashboard.py` (import block ~24; constructor ~163)
- Modify: `graphinator/graphinator.py` (import block ~13; constructor ~1345)
- Modify: `brainzgraphinator/brainzgraphinator.py` (import block ~14; constructor ~904)

- [ ] **Step 1: `api/api.py` — add import**

Change line 73 from:

```python
from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver, HealthServer, setup_logging
```

to:

```python
from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver, HealthServer, neo4j_security_kwargs, setup_logging
```

- [ ] **Step 2: `api/api.py` — apply helper at driver site**

In the `_neo4j = AsyncResilientNeo4jDriver(...)` block (~248-251), replace:

```python
            max_retries=5,
            encrypted=False,  # M3: Set encrypted=True in production with TLS-enabled Neo4j
        )
```

with:

```python
            max_retries=5,
            **neo4j_security_kwargs(),
        )
```

- [ ] **Step 3: `dashboard/dashboard.py` — add import**

In the `from common import (...)` block (~24-30), add `neo4j_security_kwargs,` so it reads:

```python
from common import (
    AsyncResilientNeo4jDriver,
    AsyncResilientPostgreSQL,
    AsyncResilientRabbitMQ,
    get_config,
    neo4j_security_kwargs,
    setup_logging,
)
```

- [ ] **Step 4: `dashboard/dashboard.py` — apply helper at driver site**

In the `self.neo4j_driver = AsyncResilientNeo4jDriver(...)` block (~160-164), replace:

```python
                max_retries=5,
                encrypted=False,
            )
```

with:

```python
                max_retries=5,
                **neo4j_security_kwargs(),
            )
```

- [ ] **Step 5: `graphinator/graphinator.py` — add import**

In the `from common import (...)` block (~13-23), add `neo4j_security_kwargs,` (after `HealthServer,`):

```python
    HealthServer,
    neo4j_security_kwargs,
    setup_logging,
)
```

- [ ] **Step 6: `graphinator/graphinator.py` — apply helper at driver site**

At the driver construction (~1342-1346), replace the line:

```python
        encrypted=False,
```

with:

```python
        **neo4j_security_kwargs(),
```

(Match the existing 8-space indentation. Confirm the surrounding call is `GraphDatabase.driver(...)` or `AsyncResilientNeo4jDriver(...)` / `ResilientNeo4jDriver(...)` — keep all other kwargs unchanged.)

- [ ] **Step 7: `brainzgraphinator/brainzgraphinator.py` — add import**

In the `from common import (...)` block (~14-24), add `neo4j_security_kwargs,` (after `HealthServer,`):

```python
    HealthServer,
    neo4j_security_kwargs,
    setup_logging,
)
```

- [ ] **Step 8: `brainzgraphinator/brainzgraphinator.py` — apply helper at driver site**

At the driver construction (~901-905), replace the line:

```python
        encrypted=False,
```

with:

```python
        **neo4j_security_kwargs(),
```

(Match the existing 8-space indentation; keep other kwargs unchanged.)

- [ ] **Step 9: Run affected service tests (no regression)**

Run: `uv run pytest tests/api tests/dashboard tests/graphinator tests/brainzgraphinator -p no:cov -q`
Expected: PASS (same counts as before — services mock the driver class; default `neo4j_security_kwargs()` returns `{}`, equivalent to the old `encrypted=False`).

- [ ] **Step 10: Lint changed files**

Run: `uv run ruff format api/api.py dashboard/dashboard.py graphinator/graphinator.py brainzgraphinator/brainzgraphinator.py && uv run ruff check api/api.py dashboard/dashboard.py graphinator/graphinator.py brainzgraphinator/brainzgraphinator.py && uv run mypy api/api.py dashboard/dashboard.py graphinator/graphinator.py brainzgraphinator/brainzgraphinator.py`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add api/api.py dashboard/dashboard.py graphinator/graphinator.py brainzgraphinator/brainzgraphinator.py
git commit -m "feat(neo4j-tls): apply TLS helper at api/dashboard/graphinator/brainzgraphinator driver sites

Replace hardcoded encrypted=False with **neo4j_security_kwargs() so Bolt
TLS becomes configurable per deployment. Default behavior unchanged (off).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Apply helper at schema-init and perftest sites

**Files:**
- Modify: `schema-init/schema_init.py` (import block ~23; constructor ~127)
- Modify: `tests/perftest/run_perftest.py` (lazy import + constructor ~102)

- [ ] **Step 1: `schema-init/schema_init.py` — add import**

Change the `from common import (...)` block (~23-27) to include `neo4j_security_kwargs,`:

```python
from common import (
    AsyncPostgreSQLPool,
    AsyncResilientNeo4jDriver,
    neo4j_security_kwargs,
    setup_logging,
)
```

- [ ] **Step 2: `schema-init/schema_init.py` — apply helper at driver site**

In `_init_neo4j()` (~127-130), replace:

```python
        driver = AsyncResilientNeo4jDriver(
            uri=NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        )
```

with:

```python
        driver = AsyncResilientNeo4jDriver(
            uri=NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            **neo4j_security_kwargs(),
        )
```

- [ ] **Step 3: `tests/perftest/run_perftest.py` — apply helper at raw driver site**

Find the block (~100-105):

```python
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            uri,
            auth=(config.get("neo4j_user", "neo4j"), config.get("neo4j_password", "")),
        )
```

Replace with (lazy import alongside the existing lazy neo4j import):

```python
        from neo4j import GraphDatabase

        from common.config import neo4j_security_kwargs

        driver = GraphDatabase.driver(
            uri,
            auth=(config.get("neo4j_user", "neo4j"), config.get("neo4j_password", "")),
            **neo4j_security_kwargs(),
        )
```

- [ ] **Step 4: Run schema-init tests (no regression)**

Run: `uv run pytest tests/schema-init -p no:cov -q`
Expected: PASS (unchanged count; `neo4j_security_kwargs()` returns `{}` by default).

- [ ] **Step 5: Lint changed files**

Run: `uv run ruff format schema-init/schema_init.py tests/perftest/run_perftest.py && uv run ruff check schema-init/schema_init.py tests/perftest/run_perftest.py && uv run mypy schema-init/schema_init.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add schema-init/schema_init.py tests/perftest/run_perftest.py
git commit -m "feat(neo4j-tls): apply TLS helper at schema-init and perftest driver sites

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Documentation

**Files:**
- Modify: `docs/configuration.md` (Neo4j env table ~155-157 + new subsection)
- Modify: `CLAUDE.md` (Environment Variables section)

- [ ] **Step 1: `docs/configuration.md` — add env-var rows**

After the `NEO4J_PASSWORD` table row (~157), add:

```markdown
| `NEO4J_TLS_ENABLED` | Encrypt the Bolt connection to Neo4j (TLS) | `false` | No |
| `NEO4J_TLS_VERIFY` | Verify the Neo4j server certificate when TLS is enabled | `true` | No |
```

- [ ] **Step 2: `docs/configuration.md` — add operator TLS subsection**

Add a new subsection (place it after the Neo4j configuration block; match the file's existing heading level):

```markdown
### Enabling TLS for Neo4j (production)

By default, services connect to Neo4j over **unencrypted Bolt** (`bolt://host:7687`),
which is acceptable only when the connection stays on a trusted host/network. For any
deployment where Bolt traffic crosses an untrusted network (separate host/VM, overlay
network, cloud), enable TLS:

- `NEO4J_TLS_ENABLED=true` — encrypt the Bolt connection.
- `NEO4J_TLS_VERIFY=true` (default) — verify the server certificate against the system CA
  bundle. Set to `false` only for self-signed/internal certificates (traffic stays
  encrypted, but the server identity is not verified — no protection against active MITM).

> **Bolt is not HTTP.** A reverse proxy that TLS-terminates the Neo4j *Browser* (HTTP, port
> 7474) does **not** secure the Bolt protocol (port 7687) these services use. To actually
> encrypt Bolt you must terminate TLS at one of:
>
> 1. **Neo4j-native Bolt TLS** — configure an SSL policy + certificate on the Neo4j server
>    (`NEO4J_dbms_ssl_policy_bolt_*`, mounted cert); services keep `bolt://neo4j:7687` and set
>    `NEO4J_TLS_ENABLED=true`. Real/CA cert → `NEO4J_TLS_VERIFY=true`; self-signed → `false`.
> 2. **Reverse-proxy TCP router** (e.g. Traefik TCP router / nginx `stream`) — add a dedicated
>    **TCP** (not HTTP) router with TLS that forwards to `neo4j:7687`; point services at that
>    endpoint with `NEO4J_HOST=<bolt-fqdn>`, `NEO4J_TLS_ENABLED=true`, `NEO4J_TLS_VERIFY=true`
>    (the proxy's managed cert validates via SNI). The proxy→Neo4j hop is then plaintext on the
>    trusted internal network.
```

- [ ] **Step 3: `CLAUDE.md` — note the new env vars**

In the "Environment Variables" section, directly after the line:

```markdown
- `NEO4J_HOST`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` — Neo4j connection
```

add:

```markdown
- `NEO4J_TLS_ENABLED`, `NEO4J_TLS_VERIFY` — opt-in Bolt TLS (default off; certificate verification on when enabled)
```

- [ ] **Step 4: Lint docs (markdown hooks)**

Run: `uv run pre-commit run --files docs/configuration.md CLAUDE.md`
Expected: PASS (or auto-fixed whitespace; re-add and re-run if a hook reformats).

- [ ] **Step 5: Commit**

```bash
git add docs/configuration.md CLAUDE.md
git commit -m "docs(neo4j-tls): document NEO4J_TLS_* vars and Bolt TLS termination options

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full lint suite**

Run: `just lint`
Expected: all pre-commit hooks pass (ruff, mypy, bandit, markdown, etc.).

- [ ] **Step 2: Run the affected test suites with coverage**

Run: `just test-common && just test-api && just test-dashboard && just test-graphinator && just test-brainzgraphinator && just test-schema-init`
Expected: all green, coverage thresholds satisfied.

- [ ] **Step 3: Confirm no stray `encrypted=False` remains**

Run: `grep -rn "encrypted=False" api dashboard graphinator brainzgraphinator schema-init tests/perftest`
Expected: no output (all replaced by `**neo4j_security_kwargs()`).

- [ ] **Step 4: Confirm clean tree and review the diff**

Run: `git status && git log --oneline origin/main..HEAD`
Expected: 4 feature commits (Tasks 1–4) on top of the spec commit; working tree clean.

---

## Self-Review Notes

- **Spec coverage:** env vars (Task 1/4), helper + behavior table + warning (Task 1), all six call sites (Tasks 2–3), test matrix (Task 1), docs incl. both termination topologies (Task 4). All spec sections mapped.
- **Out-of-scope honored:** no compose/bootstrap/Traefik files, no `NEO4J_PORT`, no `_FILE` variants.
- **Type/name consistency:** helper named `neo4j_security_kwargs` everywhere; returns `dict[str, Any]`; `TrustSystemCAs`/`TrustAll` imported from top-level `neo4j`.
