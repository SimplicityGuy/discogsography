"""SQL helpers for the digger schema, used by api/ routers.

All functions take the AsyncPostgreSQLPool plus a user_id (UUID, sourced from the
JWT 'sub' claim at the router boundary). No request body ever supplies a user_id
directly. Async psycopg3 throughout: pool.connection() -> conn.cursor() ->
cur.execute(sql, (params,)); %s placeholders, params as tuples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from psycopg.rows import dict_row


if TYPE_CHECKING:
    import uuid

    from common import AsyncPostgreSQLPool


Tier = Literal["must", "nice", "eventually"]
Cadence = Literal["off", "weekly", "biweekly", "monthly"]
Model = Literal["haiku", "sonnet", "opus"]


@dataclass(slots=True)
class UserDiggerSettings:
    user_id: uuid.UUID
    enabled: bool
    country_code: str | None
    currency: str
    scheduled_cadence: Cadence
    preferred_model: Model
    daily_token_cap_interactive: int
    daily_token_cap_scheduled: int


@dataclass(slots=True)
class WantlistPriorityRow:
    release_id: int
    tier: Tier
    min_media_condition: str
    min_sleeve_condition: str
    max_price_cents: int | None


async def get_user_settings(pool: AsyncPostgreSQLPool, user_id: uuid.UUID) -> UserDiggerSettings | None:
    """Return the digger settings for a user, or None if no row exists yet."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT user_id, enabled, country_code, currency, scheduled_cadence, "
            "preferred_model, daily_token_cap_interactive, daily_token_cap_scheduled "
            "FROM digger.user_digger_settings WHERE user_id = %s",
            (user_id,),
        )
        row = await cur.fetchone()
    return None if row is None else UserDiggerSettings(**row)


async def upsert_user_settings(
    pool: AsyncPostgreSQLPool,
    user_id: uuid.UUID,
    *,
    enabled: bool,
    country_code: str | None,
    currency: str,
    scheduled_cadence: Cadence,
    preferred_model: Model,
    daily_token_cap_interactive: int = 200_000,
    daily_token_cap_scheduled: int = 100_000,
) -> None:
    """Insert or update a user's digger settings, replacing all columns on conflict."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO digger.user_digger_settings "
            "(user_id, enabled, country_code, currency, scheduled_cadence, "
            "preferred_model, daily_token_cap_interactive, daily_token_cap_scheduled) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "enabled = EXCLUDED.enabled, country_code = EXCLUDED.country_code, "
            "currency = EXCLUDED.currency, scheduled_cadence = EXCLUDED.scheduled_cadence, "
            "preferred_model = EXCLUDED.preferred_model, "
            "daily_token_cap_interactive = EXCLUDED.daily_token_cap_interactive, "
            "daily_token_cap_scheduled = EXCLUDED.daily_token_cap_scheduled",
            (
                user_id,
                enabled,
                country_code,
                currency,
                scheduled_cadence,
                preferred_model,
                daily_token_cap_interactive,
                daily_token_cap_scheduled,
            ),
        )


async def list_wantlist_priorities(pool: AsyncPostgreSQLPool, user_id: uuid.UUID) -> list[WantlistPriorityRow]:
    """Return all wantlist priority rows for a user, ordered by tier then release id."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT release_id, tier, min_media_condition, min_sleeve_condition, max_price_cents "
            "FROM digger.user_wantlist_priorities WHERE user_id = %s ORDER BY tier, release_id",
            (user_id,),
        )
        rows = await cur.fetchall()
    return [WantlistPriorityRow(**r) for r in rows]


async def set_wantlist_priority(
    pool: AsyncPostgreSQLPool,
    user_id: uuid.UUID,
    release_id: int,
    *,
    tier: Tier | None = None,
    min_media_condition: str | None = None,
    min_sleeve_condition: str | None = None,
    max_price_cents: int | None = None,
) -> None:
    """Update only the priority fields passed as non-None for one wantlist release.

    Partial update: a None argument means "leave unchanged" — clearing a field
    back to NULL is intentionally unsupported in M1. No-op (no connection opened)
    when no fields are provided.
    """
    fields: list[str] = []
    args: list[Any] = []
    if tier is not None:
        fields.append("tier = %s")
        args.append(tier)
    if min_media_condition is not None:
        fields.append("min_media_condition = %s")
        args.append(min_media_condition)
    if min_sleeve_condition is not None:
        fields.append("min_sleeve_condition = %s")
        args.append(min_sleeve_condition)
    if max_price_cents is not None:
        fields.append("max_price_cents = %s")
        args.append(max_price_cents)
    if not fields:
        return
    fields.append("updated_at = now()")
    args.extend([user_id, release_id])
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"UPDATE digger.user_wantlist_priorities SET {', '.join(fields)} "  # noqa: S608
            "WHERE user_id = %s AND release_id = %s",
            tuple(args),
        )


async def bulk_set_tier(pool: AsyncPostgreSQLPool, user_id: uuid.UUID, release_ids: list[int], tier: Tier) -> int:
    """Set the tier for many of a user's wantlist releases at once; return rows updated."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE digger.user_wantlist_priorities SET tier = %s, updated_at = now() WHERE user_id = %s AND release_id = ANY(%s)",
            (tier, user_id, release_ids),
        )
        return cur.rowcount


async def get_wantlist_with_listings_counts(pool: AsyncPostgreSQLPool, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return a user's wantlist priorities joined with scrape state, active listing counts, and release metadata."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT uwp.release_id, uwp.tier, uwp.min_media_condition, "
            "uwp.min_sleeve_condition, uwp.max_price_cents, "
            "rs.last_scraped_at, "
            "COUNT(l.listing_id) FILTER (WHERE l.removed_at IS NULL) AS active_listings, "
            "uw.title, uw.artist, uw.year "
            "FROM digger.user_wantlist_priorities uwp "
            "LEFT JOIN digger.release_scrape_state rs ON rs.release_id = uwp.release_id "
            "LEFT JOIN digger.listings l ON l.release_id = uwp.release_id "
            "LEFT JOIN user_wantlists uw ON uw.user_id = uwp.user_id AND uw.release_id = uwp.release_id "
            "WHERE uwp.user_id = %s "
            "GROUP BY uwp.release_id, uwp.tier, uwp.min_media_condition, uwp.min_sleeve_condition, "
            "uwp.max_price_cents, rs.last_scraped_at, uw.title, uw.artist, uw.year "
            "ORDER BY uwp.tier, uw.artist NULLS LAST",
            (user_id,),
        )
        rows = await cur.fetchall()
    return list(rows)


async def list_users_due_for_report(pool: AsyncPostgreSQLPool) -> list[dict[str, Any]]:
    """Return enabled users whose scheduled cadence is on and whose next run is due (or unset)."""
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT user_id, scheduled_cadence FROM digger.user_digger_settings "
            "WHERE enabled = true AND scheduled_cadence <> 'off' "
            "AND (next_scheduled_run_at IS NULL OR next_scheduled_run_at <= now())"
        )
        rows = await cur.fetchall()
    return list(rows)
