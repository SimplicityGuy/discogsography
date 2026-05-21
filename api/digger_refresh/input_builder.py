"""Build an OptimizerInput from the digger Postgres state.

Bridges stored wantlist priorities + scraped listings/sellers into the pure
optimizer's OptimizerInput. Used by the interactive recommend endpoint and
reusable by scheduled runs. Async psycopg3 throughout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg.rows import dict_row

from api.queries.digger_queries import list_wantlist_priorities
from common.digger_optimizer.models import Listing, OptimizerInput, ReleaseConstraint, Seller, ShippingPolicyRegion


if TYPE_CHECKING:  # pragma: no cover
    import uuid

    from common import AsyncPostgreSQLPool


async def build_optimizer_input(
    pool: AsyncPostgreSQLPool,
    user_id: uuid.UUID,
    *,
    location: str,
    currency: str = "USD",
    budget_cap_cents: int | None = None,
    excluded_sellers: frozenset[int] = frozenset(),
) -> OptimizerInput:
    """Assemble the optimizer input for a user from their wantlist + scraped marketplace data."""
    priorities = await list_wantlist_priorities(pool, user_id)

    must: list[ReleaseConstraint] = []
    nice: list[ReleaseConstraint] = []
    eventually: list[ReleaseConstraint] = []
    release_ids: list[int] = []
    for p in priorities:
        rc = ReleaseConstraint(
            release_id=p.release_id,
            min_media_condition=p.min_media_condition,  # type: ignore[arg-type]  # DB enum value is a valid Condition
            min_sleeve_condition=p.min_sleeve_condition,  # type: ignore[arg-type]  # DB enum value is a valid SleeveCondition
            max_price_cents=p.max_price_cents,
        )
        release_ids.append(p.release_id)
        if p.tier == "must":
            must.append(rc)
        elif p.tier == "nice":
            nice.append(rc)
        else:
            eventually.append(rc)

    if not release_ids:
        return OptimizerInput(
            user_id=user_id,
            location=location,
            currency=currency,
            must_have_releases=[],
            nice_have_releases=[],
            eventually_releases=[],
            candidate_listings=[],
            sellers={},
            budget_cap_cents=budget_cap_cents,
            excluded_sellers=excluded_sellers,
        )

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

    sellers: dict[int, Seller] = {}
    for r in seller_rows:
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
            feedback_score=float(r["feedback_score"]) if r["feedback_score"] is not None else None,
        )

    listings = [
        Listing(
            listing_id=r["listing_id"],
            release_id=r["release_id"],
            seller_id=r["seller_id"],
            price_value=r["price_value"],
            price_currency=r["price_currency"],
            media_condition=r["media_condition"],
            sleeve_condition=r["sleeve_condition"],
        )
        for r in listing_rows
    ]

    return OptimizerInput(
        user_id=user_id,
        location=location,
        currency=currency,
        must_have_releases=must,
        nice_have_releases=nice,
        eventually_releases=eventually,
        candidate_listings=listings,
        sellers=sellers,
        budget_cap_cents=budget_cap_cents,
        excluded_sellers=excluded_sellers,
    )
