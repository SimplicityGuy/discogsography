# ⛏️ Digger Scraping Policy

<div align="center">

**How the Digger worker scrapes Discogs marketplace data — responsibly and transparently**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [🏛️ Architecture](architecture.md) | [⚙️ Configuration](configuration.md)

</div>

## Overview

**Digger** is the Discogs marketplace scraper and wantlist-intelligence worker. It tracks marketplace listings for the releases users have prioritised in their wantlist, applying each user's tier, condition, and price preferences. The worker runs on a schedule, reads and writes PostgreSQL (`digger.*` schema) and Redis directly, and exposes health plus Prometheus metrics on port **8012**. It does **not** use RabbitMQ. Its scheduler calls the API's internal Digger endpoints over HTTP (authenticated with the shared `DIGGER_API_SERVICE_TOKEN`) to generate scheduled recommendation reports.

This document describes exactly what Digger scrapes, the controls that keep request volume low and well-behaved, and the project's posture toward Discogs' Terms of Service.

## What We Scrape

Digger fetches only **public, unauthenticated** Discogs pages. It never logs in, never holds a Discogs session cookie, and never touches private, member-only, or rate-limited API endpoints.

Digger restricts itself to these public URL patterns:

| Purpose          | URL Pattern                                          | Notes                                              |
| ---------------- | ---------------------------------------------------- | -------------------------------------------------- |
| Release listings | `https://www.discogs.com/sell/release/{release_id}`  | Public marketplace listings for a release — the only page fetched in M1 |
| Seller profiles  | `https://www.discogs.com/seller/{username}`          | Public seller profile (country, feedback, shipping). Parser is implemented but the fetch is **not yet wired in M1** — seller identity uses deterministic placeholder IDs until then |

No other hosts, paths, or authenticated areas are requested. See the [Digger design spec](superpowers/specs/2026-05-14-digger-wantlist-agent-design.md) for the full feature design.

## Rate Budget

All outbound requests pass through a **Redis-backed token bucket** before they are made.

- **Default budget**: **600 requests/hour** (`DIGGER_RATE_BUDGET_PER_HOUR`).
- **Implementation**: a Redis token bucket using optimistic concurrency (`WATCH`/`MULTI`/`EXEC`) rather than Lua scripts, so it works for the single-worker M1 deployment and scales to multiple workers via the same mechanism.
- **Refill**: tokens refill continuously at `budget / 3600` tokens per second. When the bucket is empty the worker blocks until the next token is available — it never bursts past the budget.

600 requests/hour is roughly one request every six seconds — deliberately conservative for a public site.

## User-Agent

Every request carries a transparent, identifying User-Agent so Discogs can attribute (and contact about) the traffic:

```
discogsography-digger/0.1 (github.com/SimplicityGuy/discogsography)
```

Configurable via `DIGGER_SCRAPER_USER_AGENT`. Requests also send `Accept-Language: en`.

## Per-Release Backoff

When a scrape of a release fails, that release is retried with **exponential backoff**:

- Delay is `2 ** consecutive_failures` hours — failure 0 → 1 h, 1 → 2 h, 2 → 4 h, 3 → 8 h, …
- Capped at **24 hours** maximum.
- The counter resets to zero on the next successful scrape.

This is per-release state stored in `digger.release_scrape_state` (`consecutive_failures`, `next_retry_at`), so a single problematic release backs off without affecting healthy ones.

## Circuit Breaker

A global, in-memory circuit breaker protects Discogs (and Digger) from sustained failures:

| Setting          | Default | Env Var                        | Behaviour                                                  |
| ---------------- | ------- | ------------------------------ | --------------------------------------------------------- |
| Window           | `300` s | `DIGGER_CB_WINDOW_SECONDS`     | Rolling observation window for outcomes                   |
| Failure threshold | `30` %  | `DIGGER_CB_FAILURE_PCT`        | Opens when failure rate `>=` threshold (≥10 events needed) |
| Cooldown         | `1800` s | `DIGGER_CB_COOLDOWN_SECONDS`   | Stays open this long before a success can reset it         |

While the breaker is open the scrape loop pauses (sleeping in short intervals) instead of hammering a struggling endpoint. At least 10 events must be observed in the window before the breaker can trip, so a couple of isolated failures will not open it.

## SSRF Protection

The HTTP client (`digger/scraper/http_client.py`) enforces a strict **hostname allow-list** so the worker can never be redirected to an unintended target:

- **Allowed hosts**: only `www.discogs.com` and `discogs.com`.
- **Allowed schemes**: `http` and `https` only.
- **Manual redirect handling**: redirects are *not* followed automatically. Each `Location` hop is resolved against the current URL and **re-validated** against the allow-list before the next request is made. Any disallowed scheme or host raises `BlockedTargetError` and the request is abandoned.

This prevents an attacker-controlled or compromised redirect from steering the worker at internal services or arbitrary hosts.

## Listings Soft-Delete Lifecycle

Digger never hard-deletes marketplace listings. It keeps a complete, time-stamped history so price and availability trends survive across scrapes.

Each scrape of a release runs inside a single PostgreSQL transaction:

1. **Upsert** every listing observed in the scrape via `INSERT … ON CONFLICT (listing_id) DO UPDATE`, refreshing `last_seen_at` and clearing `removed_at`. `first_seen_at` is set once, on first observation, and never changes.
2. **Soft-delete** any previously-active listing for the release that was *not* seen in this scrape — its `removed_at` is set to `now()` rather than deleting the row.
3. **Reschedule** the release using an adaptive next-scrape interval.

The adaptive interval starts from a per-tier base and is scaled by recent listing churn (more activity → shorter interval, clamped to a `[0.5, 1.5]×` multiplier):

| Priority Tier | Base Interval |
| ------------- | ------------- |
| `must`        | 7 days        |
| `nice`        | 14 days       |
| `eventually`  | 28 days       |

Active-listing queries filter on `removed_at IS NULL` (backed by partial indexes), so soft-deleted rows stay out of "what's for sale now" results while remaining available for historical analysis.

## Terms of Service Posture

Digger is designed to be a low-impact, transparent, good-faith consumer of public Discogs data:

- **Public pages only** — listing and seller pages that any logged-out visitor can view. No authenticated, private, or API-rate-limited endpoints.
- **Well under any reasonable rate** — a default ceiling of 600 requests/hour (≈1 every 6 s), enforced before each request, with exponential per-release backoff and a global circuit breaker that backs off automatically when the site is unhealthy.
- **Transparent identification** — an honest, project-identifying User-Agent that links back to the source repository.
- **Respectful of failure signals** — `429` and `5xx` responses count as failures, feeding both per-release backoff and the circuit breaker so the worker eases off rather than retrying aggressively.

Operators deploying Digger are responsible for ensuring their use complies with Discogs' Terms of Service and any applicable law. These controls exist to make compliant, courteous operation the default.

## Related Documentation

- [Architecture Overview](architecture.md) — where Digger fits in the platform
- [Configuration Guide](configuration.md) — full environment-variable reference
- [Database Schema](database-schema.md) — the `digger.*` schema
- [Digger Design Spec](superpowers/specs/2026-05-14-digger-wantlist-agent-design.md) — feature design and milestones

______________________________________________________________________

**Last Updated**: 2026-05-20
