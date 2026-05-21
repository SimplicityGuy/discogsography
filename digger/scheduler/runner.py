"""Scheduled-run runner for the digger worker.

For each due user:

1. Fetch the wantlist snapshot from the API's internal endpoint (HTTP).
2. Read scraped listings + sellers for those releases directly from Postgres.
3. Run the deterministic optimizer (``common.digger_optimizer.pareto_bundles``).
4. Compute a change flag versus the user's most recent report.
5. Persist a new ``digger.reports`` row and advance ``next_scheduled_run_at``.

The worker owns the scraped marketplace tables (``listings``/``sellers``) and the
``reports`` table, so it reads/writes those directly. Wantlist priorities are
user-facing data, so they are fetched through the API's internal contract rather
than read from the table directly — keeping the worker decoupled from the API's
schema. Country/currency default to US/USD in M2 (the internal contract does not
yet expose per-user locale); cadence comes from the caller.

Async psycopg3 throughout: ``pool.connection()`` -> ``conn.cursor()`` ->
``cur.execute(sql, (params,))`` with ``%s`` placeholders. JSONB columns are
written with the psycopg ``Jsonb`` adapter and read back already parsed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import httpx
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from common.digger_optimizer import pareto_bundles
from common.digger_optimizer.models import (
    Listing,
    OptimizerInput,
    ReleaseConstraint,
    Seller,
    ShippingPolicyRegion,
)


if TYPE_CHECKING:  # pragma: no cover
    from common import AsyncPostgreSQLPool
    from common.digger_optimizer.models import OptimizerOutput

log = logging.getLogger(__name__)

ChangeFlag = Literal["first_run", "significant", "none"]

_HTTP_TIMEOUT = 10.0

# How far to push the next scheduled run after a run completes, by cadence.
_CADENCE_DELTA: dict[str, timedelta] = {
    "weekly": timedelta(days=7),
    "biweekly": timedelta(days=14),
    "monthly": timedelta(days=30),
}

# A new run differing from the prior report by at least this many listings is
# flagged "significant"; below it, "none". Boundary is inclusive (>=).
_SIGNIFICANT_CHANGE_THRESHOLD = 3

_ADVANCE_SQL = "UPDATE digger.user_digger_settings SET next_scheduled_run_at = now() + %s WHERE user_id = %s"


async def fetch_wantlist_snapshot(
    api_base_url: str, service_token: str, user_id: uuid.UUID
) -> dict[str, Any]:
    """Fetch a user's wantlist priorities (grouped by tier) from the API's internal endpoint."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{api_base_url}/api/internal/digger/wantlist-snapshot/{user_id}",
            headers={"X-Service-Token": service_token},
        )
        resp.raise_for_status()
        snapshot: dict[str, Any] = resp.json()
        return snapshot


def _constraints(rows: list[dict[str, Any]]) -> list[ReleaseConstraint]:
    return [
        ReleaseConstraint(
            release_id=r["release_id"],
            min_media_condition=r["min_media_condition"],
            min_sleeve_condition=r["min_sleeve_condition"],
            max_price_cents=r["max_price_cents"],
        )
        for r in rows
    ]


def _sellers_from_rows(rows: list[dict[str, Any]]) -> dict[int, Seller]:
    sellers: dict[int, Seller] = {}
    for r in rows:
        raw = r["shipping_policy"]
        policy = (
            {
                region: ShippingPolicyRegion(
                    first_cents=v["first_cents"],
                    additional_cents=v["additional_cents"],
                    currency=v.get("currency", "USD"),
                )
                for region, v in raw.items()
            }
            if raw
            else None
        )
        sellers[r["seller_id"]] = Seller(
            seller_id=r["seller_id"],
            region=r["region"],
            country_code=r["country_code"],
            shipping_policy=policy,
            feedback_score=float(r["feedback_score"])
            if r["feedback_score"] is not None
            else None,
        )
    return sellers


def _listings_from_rows(rows: list[dict[str, Any]]) -> list[Listing]:
    return [
        Listing(
            listing_id=r["listing_id"],
            release_id=r["release_id"],
            seller_id=r["seller_id"],
            price_value=r["price_value"],
            price_currency=r["price_currency"],
            media_condition=r["media_condition"],
            sleeve_condition=r["sleeve_condition"],
        )
        for r in rows
    ]


def _listing_ids_from_bundles(bundles: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for bundle in bundles:
        for order in bundle.get("seller_orders", []):
            for line in order.get("listings", []):
                ids.add(line["listing_id"])
    return ids


def _compute_change_flag(
    last_report_row: dict[str, Any] | None, out: OptimizerOutput
) -> ChangeFlag:
    """Classify how much a new run differs from the user's most recent report."""
    if last_report_row is None:
        return "first_run"
    prev_ids = _listing_ids_from_bundles(last_report_row.get("bundles") or [])
    cur_ids = {
        line.listing_id
        for bundle in out.bundles
        for order in bundle.seller_orders
        for line in order.listings
    }
    if len(prev_ids ^ cur_ids) >= _SIGNIFICANT_CHANGE_THRESHOLD:
        return "significant"
    return "none"


async def _advance_schedule(
    pool: AsyncPostgreSQLPool, user_id: uuid.UUID, cadence: str
) -> None:
    delta = _CADENCE_DELTA.get(cadence, _CADENCE_DELTA["weekly"])
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(_ADVANCE_SQL, (delta, user_id))


async def run_scheduled_for_user(
    pool: AsyncPostgreSQLPool,
    user_id: uuid.UUID,
    *,
    api_base_url: str,
    service_token: str,
    country: str = "US",
    currency: str = "USD",
    cadence: str = "weekly",
) -> uuid.UUID | None:
    """Generate one scheduled report for *user_id*; return its report id, or None if the wantlist is empty."""
    snapshot = await fetch_wantlist_snapshot(api_base_url, service_token, user_id)
    must = _constraints(snapshot.get("must", []))
    nice = _constraints(snapshot.get("nice", []))
    eventually = _constraints(snapshot.get("eventually", []))
    release_ids = [c.release_id for c in (*must, *nice, *eventually)]

    if not release_ids:
        log.info(
            "⏳ user %s has an empty wantlist — advancing schedule, no report generated",
            user_id,
        )
        await _advance_schedule(pool, user_id, cadence)
        return None

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT listing_id, release_id, seller_id, price_value, price_currency, media_condition, sleeve_condition "
            "FROM digger.listings WHERE release_id = ANY(%s) AND removed_at IS NULL",
            (release_ids,),
        )
        listing_rows = await cur.fetchall()
        seller_ids = list({r["seller_id"] for r in listing_rows})
        if seller_ids:
            await cur.execute(
                "SELECT seller_id, region, country_code, shipping_policy, feedback_score FROM digger.sellers WHERE seller_id = ANY(%s)",
                (seller_ids,),
            )
            seller_rows = await cur.fetchall()
        else:
            seller_rows = []
        await cur.execute(
            "SELECT bundles FROM digger.reports WHERE user_id = %s ORDER BY generated_at DESC LIMIT 1",
            (user_id,),
        )
        last_report = await cur.fetchone()

    listings = _listings_from_rows(listing_rows)
    sellers = _sellers_from_rows(seller_rows)

    optimizer_input = OptimizerInput(
        user_id=user_id,
        location=country,
        currency=currency,
        must_have_releases=must,
        nice_have_releases=nice,
        eventually_releases=eventually,
        candidate_listings=listings,
        sellers=sellers,
    )
    out = pareto_bundles(optimizer_input)
    change_flag = _compute_change_flag(last_report, out)

    available_releases = {listing.release_id for listing in listings}
    summary = {
        "wantlist_size": len(release_ids),
        "must_available": sum(1 for c in must if c.release_id in available_releases),
        "total_value_cents": out.bundles[0].grand_total_cents if out.bundles else 0,
    }
    report_id = uuid.uuid4()
    title = f"Scheduled report — {datetime.now(UTC).date().isoformat()}"
    delta = _CADENCE_DELTA.get(cadence, _CADENCE_DELTA["weekly"])

    async with pool.connection() as conn:
        await conn.set_autocommit(False)
        async with conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO digger.reports "
                "(report_id, user_id, kind, title, summary, bundles, watching, change_flag, shipping_confidence) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    report_id,
                    user_id,
                    "scheduled",
                    title,
                    Jsonb(summary),
                    Jsonb([b.model_dump(mode="json") for b in out.bundles]),
                    Jsonb(out.watching),
                    change_flag,
                    out.shipping_confidence,
                ),
            )
            await cur.execute(_ADVANCE_SQL, (delta, user_id))

    log.info(
        "💾 generated scheduled report for user %s (change=%s)", user_id, change_flag
    )
    return report_id
