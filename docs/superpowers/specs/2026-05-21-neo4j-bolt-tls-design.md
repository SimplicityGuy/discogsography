# Neo4j Bolt TLS Support (client-side)

## Overview

Resolve GitHub issue [#74](https://github.com/SimplicityGuy/discogsography/issues/74) —
`security(M3): enable Neo4j TLS for non-local deployments`.

Today every service connects to Neo4j over the **Bolt** binary protocol (`bolt://{host}:7687`)
with `encrypted=False`, so all graph traffic (queries, writes, user data) crosses the network
in plaintext. This is fine on a single Docker host (bridge traffic is host-local) but exposes
data when the Bolt hop traverses an untrusted network — a separate-host/VM Neo4j, an overlay
network, or a cloud deployment.

This work delivers the **client-side enabler**: opt-in, configurable TLS for the Bolt connection,
secure-by-default when enabled. It is the prerequisite for every TLS topology but does not, by
itself, encrypt anything — the Bolt endpoint must also offer TLS (see *Deployment topologies*).

## Scope

**In scope**

- Two boolean env vars: `NEO4J_TLS_ENABLED` (default `false`), `NEO4J_TLS_VERIFY` (default `true`).
- One shared helper in `common/config.py` that maps those vars to neo4j driver security kwargs.
- Apply the helper at all six Neo4j driver construction sites.
- Unit tests for the helper.
- Operator documentation covering both server-side TLS termination options.

**Out of scope (explicitly)**

- Neo4j **server-side** TLS provisioning (SSL policy, certificate issuance/mounting) — infrastructure.
- A `docker-compose.tls.yml` overlay, Traefik dynamic config, or any homelab bootstrap — separate, larger deliverable. May be a follow-up issue.
- `NEO4J_PORT` (the URI stays `:7687`); not needed for the in-scope topologies.
- `_FILE` secret variants — these are booleans, not secrets.

## Background: neo4j-python-driver 6.2.0 API

The pinned driver is `neo4j==6.2.0`. Verified against the installed package:

- Driver security is configured with **two kwargs**: `encrypted: bool` and
  `trusted_certificates: TrustStore`. The legacy string `trust=` parameter no longer exists.
- `TrustStore` implementations: `TrustSystemCAs()` (verify against system CA bundle — default),
  `TrustAll()` (encrypt but do **not** verify server identity), `TrustCustomCAs(*paths)`.
- **Hard constraint:** `encrypted` / `trusted_certificates` **cannot** be combined with a secure
  URI scheme (`bolt+s://`, `bolt+ssc://`, `neo4j+s://`, `neo4j+ssc://`). Doing so raises a
  `ConfigurationError`. Therefore the design keeps the plain `bolt://` scheme and expresses TLS
  purely through kwargs.
- For a plain `bolt://` URI, omitting `encrypted` defaults to unencrypted — so "TLS disabled"
  is behaviorally identical to today's explicit `encrypted=False`.

## Approach

**Approach A (chosen): driver kwargs via a shared helper.**

Keep `bolt://` URIs. Add one helper that reads the two env vars and returns the security kwargs.
Replace every `encrypted=False` with `**neo4j_security_kwargs()`. One tested function, greppable
at every call site, maps directly onto the configurable-verify model.

Rejected alternatives:

- **Secure URI schemes** (`bolt+s://` / `bolt+ssc://`): the driver forbids combining a secure
  scheme with the `encrypted`/`trusted_certificates` kwargs, so we'd lose the explicit verify
  toggle and inherit a coarser, scheme-encoded trust model.
- **TLS fields on each config dataclass**: duplicates the same two fields across 4+ dataclasses
  and doesn't cover the raw (non-dataclass) perftest call site. A shared helper covers all sites
  uniformly.

## Design

### Environment variables

| Variable            | Default | Meaning                                                                 |
| ------------------- | ------- | ----------------------------------------------------------------------- |
| `NEO4J_TLS_ENABLED` | `false` | When `true`, the Bolt connection is encrypted (`encrypted=True`).       |
| `NEO4J_TLS_VERIFY`  | `true`  | When TLS enabled: `true` → verify cert against system CAs; `false` → trust all certs (encrypted, identity unverified). Ignored when TLS disabled. |

Booleans are parsed with the project's existing convention: `value.strip().lower() == "true"`
(mirrors `NEO4J_BATCH_MODE`). Only the literal `true` (case-insensitive) enables; everything
else, including unset, is `false`.

### Helper: `common/config.py`

```python
def neo4j_security_kwargs() -> dict[str, Any]:
    """Return neo4j driver security kwargs derived from NEO4J_TLS_* env vars.

    - TLS disabled  -> {}                 (plaintext bolt://, unchanged behavior)
    - enabled+verify-> {"encrypted": True, "trusted_certificates": TrustSystemCAs()}
    - enabled+!verify-> {"encrypted": True, "trusted_certificates": TrustAll()}  (+ warning)
    """
```

Behavior table:

| `NEO4J_TLS_ENABLED` | `NEO4J_TLS_VERIFY` | Returned kwargs                                              | Log    |
| ------------------- | ------------------ | ----------------------------------------------------------- | ------ |
| false (or unset)    | (any)              | `{}`                                                        | —      |
| true                | true (or unset)    | `{"encrypted": True, "trusted_certificates": TrustSystemCAs()}` | info 🔒 |
| true                | false              | `{"encrypted": True, "trusted_certificates": TrustAll()}`   | warn ⚠️ |

- Imports `from neo4j import TrustAll, TrustSystemCAs` (top-level neo4j exports).
- The `verify=false` branch logs a **one-line WARNING** (emoji per `docs/emoji-guide.md`) that
  traffic is encrypted but the server identity is unverified (no MITM protection).
- The `enabled+verify` branch logs an INFO confirming TLS is active.
- Logging happens at kwargs-construction time (driver init), which is once per service start.

### Call sites

Replace `encrypted=False` (or add the spread where none exists) with `**neo4j_security_kwargs()`.
The two resilient drivers already forward `**driver_kwargs` to `GraphDatabase.driver(...)`, so no
driver-class changes are required.

| File                                      | Current                            | Change                                  |
| ----------------------------------------- | ---------------------------------- | --------------------------------------- |
| `api/api.py` (~250)                        | `encrypted=False,  # M3 ...`       | `**neo4j_security_kwargs(),`            |
| `dashboard/dashboard.py` (~163)           | `encrypted=False,`                 | `**neo4j_security_kwargs(),`            |
| `graphinator/graphinator.py` (~1345)      | `encrypted=False,`                 | `**neo4j_security_kwargs(),`            |
| `brainzgraphinator/brainzgraphinator.py` (~904) | `encrypted=False,`           | `**neo4j_security_kwargs(),`            |
| `schema-init/schema_init.py` (~128)       | (no `encrypted` kwarg)             | add `**neo4j_security_kwargs(),`        |
| `tests/perftest/run_perftest.py` (~102)   | raw `GraphDatabase.driver(...)`    | add `**neo4j_security_kwargs(),`        |

Each call site imports the helper from `common.config` (perftest may import lazily as it already
imports neo4j lazily). The default behavior (`{}`) is byte-for-byte equivalent to the prior
`encrypted=False`, so local dev and existing e2e/live-stack runs are unaffected.

### Testing

New unit tests in `tests/common/test_config.py` (or a focused new module) using `monkeypatch`:

- unset → `{}`
- `NEO4J_TLS_ENABLED=false` → `{}` (and `NEO4J_TLS_VERIFY` ignored)
- `NEO4J_TLS_ENABLED=true` (verify unset) → `encrypted=True`, `trusted_certificates` is `TrustSystemCAs`
- `NEO4J_TLS_ENABLED=true`, `NEO4J_TLS_VERIFY=true` → `TrustSystemCAs`
- `NEO4J_TLS_ENABLED=true`, `NEO4J_TLS_VERIFY=false` → `TrustAll` (+ assert WARNING emitted via `caplog`)
- boolean-parse edges: `TRUE`, `True`, `1`, `yes`, ` true ` → only case-insensitive `true` enables
- assert returned `trusted_certificates` is an **instance** of the expected `TrustStore` subclass

TDD: write these tests first (red), implement the helper (green), then apply at call sites.
Maintain >80% coverage (helper is fully covered by the above).

### Documentation

- **`docs/configuration.md`**: add `NEO4J_TLS_ENABLED` / `NEO4J_TLS_VERIFY` to the Neo4j env-var
  table and the example blocks; add a short **"Enabling TLS for Neo4j (production)"** subsection
  documenting the two server-side termination options below.
- **`CLAUDE.md`** (Environment Variables section): note the two new optional vars.
- Mermaid for any diagram, per repo convention.

## Deployment topologies (operator docs content)

Bolt is **not** HTTP. A reverse proxy that TLS-terminates the Neo4j *Browser* (port 7474, e.g.
`https://neo4j.example`) does **not** secure the Bolt protocol (port 7687) that these services use.
To actually encrypt Bolt, terminate TLS at one of:

1. **Neo4j-native Bolt TLS.** Configure an SSL policy + certificate on the Neo4j server
   (`NEO4J_dbms_ssl_policy_bolt_*`, mounted cert). Services keep `bolt://neo4j:7687` and set
   `NEO4J_TLS_ENABLED=true`. Real/CA cert → `NEO4J_TLS_VERIFY=true`; self-signed/internal cert →
   `NEO4J_TLS_VERIFY=false`.
2. **Reverse-proxy TCP router (e.g. Traefik/nginx stream).** Add a dedicated **TCP** (not HTTP)
   router with TLS that forwards to `neo4j:7687`. Point services at that endpoint
   (`NEO4J_HOST=<bolt-fqdn>`, `NEO4J_TLS_ENABLED=true`, `NEO4J_TLS_VERIFY=true` — the proxy's
   managed cert validates via SNI). The proxy→Neo4j hop is then plaintext on the trusted internal
   network.

## Security considerations

- Default-off preserves local/dev behavior; opt-in only.
- Default-verify-on means enabling TLS is secure by default; weakening to `TrustAll()` is an
  explicit operator choice and is logged as a warning.
- `TrustAll()` defends against passive interception (issue #74's stated threat) but not active
  MITM; the docs state this trade-off and recommend `verify=true` with a proper cert.
- No secrets are introduced; the new vars are non-sensitive booleans.

## Files touched

- `common/config.py` — add `neo4j_security_kwargs()` (+ neo4j TrustStore imports).
- `api/api.py`, `dashboard/dashboard.py`, `graphinator/graphinator.py`,
  `brainzgraphinator/brainzgraphinator.py`, `schema-init/schema_init.py`,
  `tests/perftest/run_perftest.py` — apply helper at driver construction.
- `tests/common/test_config.py` — helper unit tests.
- `docs/configuration.md`, `CLAUDE.md` — env vars + operator TLS guide.
