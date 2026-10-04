"""Published collection-sync projections, never snapshots of partially synced live rows."""

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from typing import Any
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary, ref

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException
from psycopg.rows import dict_row


_GLOBAL_LOCK = (163418, 731)
_HEADER_BYTES = 256


@dataclass(frozen=True)
class Limits:
    """Limits include building stages; metadata consumes one row and 256 bytes."""

    items: int = 100_000
    bytes: int = 64 * 1024 * 1024
    generations: int = 8
    global_rows: int = 2_000_000
    global_bytes: int = 1024 * 1024 * 1024
    producers: int = 2
    ttl_seconds: int = 900

    @classmethod
    def from_env(cls) -> "Limits":
        values = {name: int(os.getenv("COLLECTION_SNAPSHOT_" + name.upper(), str(default))) for name, default in cls().__dict__.items()}
        if any(value <= 0 for value in values.values()):
            raise ValueError("Collection snapshot limits must be positive")
        return cls(**values)


class ProducerUnavailable(RuntimeError):
    """Safe capacity/configuration/ownership failure before publishing a generation."""


@asynccontextmanager
async def transaction(conn: Any) -> AsyncIterator[None]:
    """Keep owner connections out of transactions during upstream network waits."""
    await conn.set_autocommit(False)
    try:
        async with conn.transaction():
            yield
    finally:
        if not conn.closed:
            await conn.set_autocommit(True)


async def user_lock(conn: Any, owner: str) -> bool:
    row = await (await conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0))", ("collection-generation:" + owner,))).fetchone()
    return bool(row[0])


async def release_user_lock(conn: Any, owner: str) -> None:
    try:
        async with asyncio.timeout(5):
            row = await (await conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", ("collection-generation:" + owner,))).fetchone()
            if not row[0]:
                raise RuntimeError("Collection producer lock was not held")
    except BaseException:
        # A session with uncertain ownership must never return to the pool.
        await conn.close()
        raise


def snapshot_error(code: str, status: int = 409) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": "Collection snapshot is unavailable or does not match this request"})


class CollectionGenerations:
    def __init__(self, pool: Any, limits: Limits | None = None) -> None:
        self._pool = ref(pool)
        self.limits = limits or Limits.from_env()
        self._admission_lock: asyncio.Lock | None = None
        self._active = 0

    @property
    def pool(self) -> Any:
        pool = self._pool()
        if pool is None:
            raise RuntimeError("Collection generation pool is no longer available")
        return pool

    @asynccontextmanager
    async def admission(self) -> AsyncIterator[None]:
        if self.pool.max_connections < 2:
            raise ProducerUnavailable("Collection generation producer requires POSTGRES_POOL_MAX_SIZE >= 2")
        if self._admission_lock is None:
            self._admission_lock = asyncio.Lock()
        async with self._admission_lock:
            if self._active >= min(self.limits.producers, self.pool.max_connections - 1):
                raise ProducerUnavailable("Collection generation producer capacity is busy")
            self._active += 1
        try:
            yield
        finally:
            async with self._admission_lock:
                self._active -= 1

    async def global_lock(self, conn: Any) -> None:
        await conn.execute("SELECT pg_advisory_xact_lock(%s,%s)", _GLOBAL_LOCK)

    async def cleanup(self, conn: Any) -> None:
        """Caller holds global transaction lock; never wait for a producer lock."""
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""
                SELECT g.id,g.user_id,g.status FROM collection_generations g
                WHERE NOT EXISTS(SELECT 1 FROM collection_current c WHERE c.generation_id=g.id)
                  AND (g.status='building' OR g.retain_until<=clock_timestamp())
                ORDER BY g.started_at LIMIT 32 FOR UPDATE SKIP LOCKED
            """)
            candidates = await cur.fetchall()
        for candidate in candidates:
            owner = str(candidate["user_id"])
            if not await user_lock(conn, owner):
                continue
            try:
                await conn.execute("DELETE FROM collection_generations WHERE id=%s", (candidate["id"],))
            finally:
                await release_user_lock(conn, owner)

    async def capacity(self, conn: Any, generation: UUID) -> None:
        row = await (
            await conn.execute(
                """
            SELECT g.total,g.payload_bytes,
              (SELECT count(*) FROM collection_generations WHERE user_id=g.user_id),
              (SELECT COALESCE(sum(total+1),0) FROM collection_generations),
              (SELECT COALESCE(sum(payload_bytes),0) FROM collection_generations)
            FROM collection_generations g WHERE g.id=%s
        """,
                (generation,),
            )
        ).fetchone()
        if row is None or any(
            value > limit
            for value, limit in zip(
                row,
                (
                    self.limits.items,
                    self.limits.bytes,
                    self.limits.generations,
                    self.limits.global_rows,
                    self.limits.global_bytes,
                ),
                strict=True,
            )
        ):
            raise ProducerUnavailable("Collection generation storage capacity exceeded")

    @asynccontextmanager
    async def producer(self, owner: str) -> AsyncIterator[tuple[Any, UUID]]:
        async with self.admission(), self.pool.connection() as conn:
            acquired: bool | None = None
            generation = uuid4()
            try:
                acquired = await user_lock(conn, owner)
                if not acquired:
                    raise ProducerUnavailable("Collection generation producer is already running for this user")
                async with transaction(conn):
                    await self.global_lock(conn)
                    await self.cleanup(conn)
                    await conn.execute(
                        """
                        INSERT INTO collection_generations(id,user_id,status,payload_bytes)
                        VALUES(%s,%s,'building',%s)
                    """,
                        (generation, owner, _HEADER_BYTES),
                    )
                    await self.capacity(conn, generation)
                yield conn, generation
            finally:
                # Original failures/cancellation survive cleanup. If unlock fails,
                # release_user_lock closes the session, which releases its locks.
                if acquired is not False:
                    try:
                        await release_user_lock(conn, owner)
                    except BaseException:
                        if not conn.closed:
                            await conn.close()

    async def stage(self, conn: Any, generation: UUID, rows: list[dict[str, Any]]) -> None:
        """Called inside the SAME global-locked transaction as live page upserts."""
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO collection_generation_items(generation_id,release_id,instance_id,date_added,payload)
                SELECT %s,%s,%s,%s,%s::jsonb
                WHERE EXISTS(SELECT 1 FROM collection_generations WHERE id=%s AND status='building')
                ON CONFLICT(generation_id,release_id,instance_id) DO UPDATE SET
                    date_added=EXCLUDED.date_added,payload=EXCLUDED.payload
            """,
                [self._item_params(generation, row) for row in rows],
            )
        await conn.execute(
            """
            UPDATE collection_generations SET
                total=(SELECT count(*) FROM collection_generation_items WHERE generation_id=%s),
                payload_bytes=%s+(SELECT COALESCE(sum(pg_column_size(payload)),0) FROM collection_generation_items WHERE generation_id=%s)
            WHERE id=%s AND status='building'
        """,
            (generation, _HEADER_BYTES, generation, generation),
        )
        await self.capacity(conn, generation)

    @staticmethod
    def _item_params(generation: UUID, row: dict[str, Any]) -> tuple[Any, ...]:
        payload = dict(row)
        release = payload.pop("release_id")
        metadata = payload.pop("metadata") or {}
        payload["id"] = str(release)
        payload["catalog_number"] = metadata.get("catalog_number") if metadata.get("canonical_pair_source") == "first-label" else None
        if metadata.get("canonical_pair_source") != "first-label":
            payload["label"] = None
        date = payload["date_added"]
        payload["date_added"] = date.isoformat() if date else None
        return generation, release, payload["instance_id"], date, json.dumps(payload), generation

    async def publish(self, conn: Any, generation: UUID) -> None:
        async with transaction(conn):
            await self.global_lock(conn)
            await conn.execute(
                """
                WITH ordered AS (
                  SELECT id,row_number() OVER(ORDER BY date_added DESC NULLS LAST,release_id,instance_id NULLS LAST)-1 AS ordinal
                  FROM collection_generation_items WHERE generation_id=%s
                ) UPDATE collection_generation_items i SET ordinal=o.ordinal FROM ordered o WHERE i.id=o.id
            """,
                (generation,),
            )
            await conn.execute(
                """
                UPDATE collection_generations SET status='published',published_at=clock_timestamp() WHERE id=%s AND status='building'
            """,
                (generation,),
            )
            await conn.execute(
                """
                INSERT INTO collection_current(user_id,generation_id)
                SELECT user_id,id FROM collection_generations WHERE id=%s AND status='published'
                ON CONFLICT(user_id) DO UPDATE SET generation_id=EXCLUDED.generation_id
            """,
                (generation,),
            )

    async def page(self, owner: str, snapshot: str, expected: str | None, limit: int, offset: int, secret: str) -> dict[str, Any]:
        codec = self.codec(secret)
        if snapshot == "new":
            if offset != 0 or expected is not None:
                raise snapshot_error("snapshot_mismatch")
            async with self.pool.connection() as conn, transaction(conn):
                await self.global_lock(conn)
                await self.cleanup(conn)
                expires = (datetime.now(UTC) + timedelta(seconds=self.limits.ttl_seconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")
                row = await (
                    await conn.execute(
                        """
                    UPDATE collection_generations g SET retain_until=GREATEST(g.retain_until,%s::timestamptz)
                    FROM collection_current c WHERE c.user_id=%s AND c.generation_id=g.id AND g.status='published'
                    RETURNING g.id
                """,
                        (expires, owner),
                    )
                ).fetchone()
                if row is None:
                    raise snapshot_error("snapshot_unavailable")
                generation = str(row[0])
            token = codec.encrypt(json.dumps({"owner": owner, "generation": generation, "expires": expires}).encode()).decode()
        else:
            token = snapshot
            claims = self.claims(codec, token)
            generation, expires = claims["generation"], claims["expires"]
            if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.now(UTC):
                raise snapshot_error("snapshot_expired", 410)
            if claims["owner"] != owner:
                raise snapshot_error("snapshot_scope_mismatch")
            if expected != generation:
                raise snapshot_error("snapshot_mismatch")
        # One SQL statement gives a coherent MVCC read even if a token expires
        # while cleanup runs; separate total/items statements could tear.
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    """
                SELECT g.total,COALESCE(jsonb_agg(i.payload ORDER BY i.ordinal)
                    FILTER(WHERE i.id IS NOT NULL),'[]'::jsonb)
                FROM collection_generations g
                LEFT JOIN LATERAL (
                    SELECT id,payload,ordinal FROM collection_generation_items
                    WHERE generation_id=g.id AND ordinal>=%s AND ordinal<%s
                    ORDER BY ordinal
                ) i ON true
                WHERE g.id=%s AND g.user_id=%s AND g.status='published'
                GROUP BY g.id,g.total
            """,
                    (offset, offset + limit, generation, owner),
                )
            ).fetchone()
            if row is None:
                raise snapshot_error("snapshot_mismatch")
        items = row[1]
        if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.now(UTC):
            raise snapshot_error("snapshot_expired", 410)
        return {
            "user_id": owner,
            "releases": items,
            "total": row[0],
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < row[0],
            "snapshot_token": token,
            "snapshot_generation": generation,
            "snapshot_expires_at": expires,
            "snapshot_source": "completed_collection_sync",
        }

    @staticmethod
    def codec(secret: str) -> Fernet:
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"collection-snapshot-v1").derive(secret.encode())
        return Fernet(base64.urlsafe_b64encode(key))

    @staticmethod
    def claims(codec: Fernet, token: str) -> dict[str, str]:
        try:
            claims = json.loads(codec.decrypt(token.encode()))
            if not isinstance(claims, dict) or not all(isinstance(claims.get(key), str) for key in ("owner", "generation", "expires")):
                raise ValueError("Malformed snapshot")
            UUID(claims["owner"])
            UUID(claims["generation"])
            if datetime.fromisoformat(claims["expires"].replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("Malformed snapshot expiry")
        except (InvalidToken, ValueError, TypeError, AssertionError, UnicodeError):
            raise snapshot_error("snapshot_mismatch") from None
        return claims


_stores: WeakKeyDictionary[Any, CollectionGenerations] = WeakKeyDictionary()


def get_store(pool: Any) -> CollectionGenerations:
    if pool not in _stores:
        _stores[pool] = CollectionGenerations(pool)
    return _stores[pool]
