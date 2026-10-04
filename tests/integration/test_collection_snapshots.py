"""Real immutable-generation producer/HTTP controls on explicitly owned PG+Neo4j."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import logging
import os
import socket
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
import httpx
import psycopg
from psycopg import sql
import pytest
import pytest_asyncio
import uvicorn

from api import app_tokens, dependencies, syncer
from api.app_tokens import generate_plaintext_token, hash_token
from api.auth import b64url_encode
from api.collection_generations import CollectionGenerations, ProducerUnavailable, get_store, release_user_lock, transaction, user_lock
from api.routers import user
from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver
from common.snapshot_logging import install_snapshot_log_redaction
from postgres_schema import _USER_TABLES, create_postgres_schema
from tests.perftest.run_perftest import run_collection_snapshot_perf


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
OWNER = UUID("00000000-0000-0000-0000-000000000011")
OTHER = UUID("00000000-0000-0000-0000-000000000012")
SECRET = "synthetic-snapshot-secret"


@pytest_asyncio.fixture
async def store(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> AsyncIterator[Any]:
    assert os.getenv("DGS_SNAPSHOTS_ISOLATED") == "1", "Explicitly owned databases are required"
    parent = os.environ["DGS_SNAPSHOTS_POSTGRES_DSN"]
    name = "snap_" + uuid4().hex
    with psycopg.connect(parent, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = {**psycopg.conninfo.conninfo_to_dict(parent), "dbname": name}
    selected = getattr(request, "param", 3)
    pool = AsyncPostgreSQLPool(params, min_connections=1, max_connections=selected if isinstance(selected, int) else 3)
    await pool.initialize()
    driver = AsyncResilientNeo4jDriver(os.environ["DGS_SNAPSHOTS_NEO4J_URI"], ("neo4j", os.environ["DGS_SNAPSHOTS_NEO4J_PASSWORD"]))
    tokens = []
    try:
        async with pool.connection() as conn:
            definitions = [
                (name, ddl)
                for name, ddl in _USER_TABLES
                if selected != "legacy" or not name.startswith(("collection_generation", "collection_current", "idx_collection_generation"))
            ]
            for _name, ddl in definitions:
                await conn.execute(ddl)
            # Rerun exact upgrade statements: no copying live rows/duplicating schema.
            for _name, ddl in definitions:
                await conn.execute(ddl)
            for owner in (OWNER, OTHER):
                await conn.execute("INSERT INTO users(id,email,hashed_password) VALUES(%s,%s,'synthetic')", (owner, str(owner) + "@example.invalid"))
                token = generate_plaintext_token()
                tokens.append(token)
                await conn.execute(
                    "INSERT INTO app_tokens(user_id,name,scope,token_hash) VALUES(%s,'Synthetic proof',%s,%s)",
                    (owner, ["collection:read"], hash_token(token)),
                )
        async with driver.session() as session:
            await (await session.run("MATCH(n) DETACH DELETE n")).consume()
        dependencies.configure(SECRET, pool=pool)
        app_tokens.configure(pool)
        user.configure(driver, SECRET, pool)
        monkeypatch.setattr(user.limiter, "enabled", False)
        app = FastAPI()
        app.include_router(user.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://owned", headers={"Authorization": "Bearer " + tokens[0]}
        ) as client:
            yield driver, pool, client, tokens, params
    finally:
        if app_tokens._background_tasks:
            await asyncio.gather(*tuple(app_tokens._background_tasks))
        await pool.close()
        async with driver.session() as session:
            await (await session.run("MATCH(n) DETACH DELETE n")).consume()
        await driver.close()
        with psycopg.connect(parent, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def item(release: int, instance: int | None = None, date: str | None = "2026-01-01T00:00:00Z", **basic: Any) -> dict[str, Any]:
    return {
        "instance_id": instance if instance is not None else release,
        "folder_id": 1,
        "rating": 4,
        "date_added": date,
        "basic_information": {
            "id": release,
            "title": f"Album {release}",
            "artists": [{"name": "Artist"}],
            "year": 2000,
            "labels": [{"name": "First label", "catno": f"CAT-{release}"}],
            "formats": [{"name": "Vinyl"}],
            **basic,
        },
    }


async def publish(
    store: Any,
    monkeypatch: pytest.MonkeyPatch,
    pages: list[list[dict[str, Any]]],
    owner: UUID = OWNER,
    failure: int | None = None,
    waiting: tuple[asyncio.Event, asyncio.Event] | tuple[asyncio.Event, asyncio.Event, int] | None = None,
) -> int:
    driver, pool, *_ = store
    async with driver.session() as session:
        ids = sorted({str(row["basic_information"]["id"]) for page in pages for row in page})
        await (await session.run("UNWIND $ids AS id MERGE(:Release{id:id})", ids=ids)).consume()
    real_client = httpx.AsyncClient

    async def respond(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        if waiting and page == (waiting[2] if len(waiting) == 3 else 1):
            waiting[0].set()
            await waiting[1].wait()
        return httpx.Response(503 if page == failure else 200, json={"releases": pages[page - 1], "pagination": {"pages": len(pages)}})

    with monkeypatch.context() as patch:
        patch.setattr(syncer.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
        patch.setattr(syncer, "SYNC_DELAY_SECONDS", 0)
        return await syncer.sync_collection(owner, "synthetic", "key", "secret", "access", "token", "test", pool, driver)


async def first(client: httpx.AsyncClient, limit: int = 2) -> dict[str, Any]:
    response = await client.get("/api/user/collection", params={"snapshot": "new", "limit": limit})
    assert response.status_code == 200, response.text
    data = response.json()
    assert str(UUID(data["snapshot_generation"])) == data["snapshot_generation"]
    assert data["snapshot_expires_at"].endswith("Z")
    assert data["snapshot_source"] == "completed_collection_sync"
    return data


def continuation(data: dict[str, Any], offset: int = 2, limit: int = 2) -> dict[str, Any]:
    return {"snapshot": data["snapshot_token"], "snapshot_generation": data["snapshot_generation"], "offset": offset, "limit": limit}


async def test_immutable_membership_payload_order_and_new_publication(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, pool, client, *_ = store
    original = [item(1, 11), item(1, 12), item(2), item(3), item(4, date=None)]
    await publish(store, monkeypatch, [original[:2], original[2:]])
    a = await first(client)
    assert [(r["id"], r["instance_id"]) for r in a["releases"]] == [("1", 11), ("1", 12)]
    assert (a["releases"][0]["label"], a["releases"][0]["catalog_number"]) == ("First label", "CAT-1")
    # Mutate both live stores while the old snapshot is pinned; equal total is no oracle.
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM user_collections WHERE release_id=2")
        await conn.execute("UPDATE user_collections SET title='Changed',date_added=clock_timestamp()")
    async with driver.session() as session:
        await (await session.run("MATCH(r:Release{id:'2'}) DETACH DELETE r")).consume()
    changed = [item(9), item(3, title="Changed"), item(1, 12), item(4), item(8)]
    await publish(store, monkeypatch, [changed])
    rows = a["releases"][:]
    for offset in (2, 4):
        b = (await client.get("/api/user/collection", params=continuation(a, offset))).json()
        for key in ("snapshot_token", "snapshot_generation", "snapshot_expires_at", "snapshot_source", "total"):
            assert b[key] == a[key]
        rows.extend(b["releases"])
    assert [(r["id"], r["instance_id"]) for r in rows] == [("1", 11), ("1", 12), ("2", 2), ("3", 3), ("4", 4)]
    assert all(r["title"].startswith("Album") for r in rows)
    fresh = await first(client, 200)
    assert fresh["snapshot_generation"] != a["snapshot_generation"]
    assert {r["id"] for r in fresh["releases"]} == {"1", "3", "4", "8", "9"}
    assert (await get_store(pool).page(str(OWNER), a["snapshot_token"], a["snapshot_generation"], 200, 0, SECRET))["releases"] == rows
    # New service/store instance after restart still reads persisted generation.
    assert (await CollectionGenerations(pool).page(str(OWNER), a["snapshot_token"], a["snapshot_generation"], 200, 0, SECRET))["releases"] == rows


async def test_no_bootstrap_empty_single_and_repeated_source_instances(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO user_collections(user_id,release_id,label,metadata) VALUES(%s,99,'Unproven','{\"catalog_number\":\"WRONG\"}')", (OWNER,)
        )
    response = await client.get("/api/user/collection", params={"snapshot": "new"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "snapshot_unavailable"
    await publish(store, monkeypatch, [[item(99, labels=[]), item(99, labels=[])]])
    a = await first(client, 200)
    assert a["total"] == 1 and not a["has_more"]
    assert (a["releases"][0]["label"], a["releases"][0]["catalog_number"]) == (None, None)
    await publish(store, monkeypatch, [[]])
    empty = await first(client)
    assert empty["total"] == 0 and empty["releases"] == [] and not empty["has_more"]


@pytest.mark.parametrize(
    "kind,code,status",
    [
        ("tamper", "snapshot_mismatch", 409),
        ("generation", "snapshot_mismatch", 409),
        ("missing", "snapshot_mismatch", 409),
        ("owner", "snapshot_scope_mismatch", 409),
        ("expired", "snapshot_expired", 410),
    ],
)
async def test_authenticated_tagged_rejections(store: Any, monkeypatch: pytest.MonkeyPatch, kind: str, code: str, status: int) -> None:
    _driver, pool, client, tokens, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    params = continuation(a, 0)
    if kind == "tamper":
        params["snapshot"] = "not-a-token"
    if kind == "generation":
        params["snapshot_generation"] = str(uuid4())
    if kind == "missing":
        params.pop("snapshot_generation")
    if kind == "owner":
        client.headers["Authorization"] = "Bearer " + tokens[1]
    if kind == "expired":
        codec = get_store(pool).codec(SECRET)
        claims = get_store(pool).claims(codec, a["snapshot_token"])
        claims["expires"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        params["snapshot"] = codec.encrypt(json.dumps(claims).encode()).decode()
    response = await client.get("/api/user/collection", params=params)
    assert response.status_code == status and response.json()["detail"]["code"] == code
    assert params["snapshot"] not in response.text
    client.headers["Authorization"] = "Bearer invalid-credential"
    assert (await client.get("/api/user/collection", params=params)).status_code == 401


async def test_failed_and_cancelled_generation_preserve_pointer_and_release_lock(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    with pytest.raises(syncer.DiscogsSyncError):
        await publish(store, monkeypatch, [[item(2)], [item(3)]], failure=2)
    assert (await first(client))["snapshot_generation"] == a["snapshot_generation"]
    started, release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(publish(store, monkeypatch, [[item(4)]], waiting=(started, release)))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with pool.connection() as conn:
        assert await user_lock(conn, str(OWNER))
        await release_user_lock(conn, str(OWNER))
    assert get_store(pool)._active == 0
    assert (await first(client))["snapshot_generation"] == a["snapshot_generation"]


@pytest.mark.parametrize("store", [2], indirect=True)
async def test_reserved_pool_slot_minimum_and_busy_controls(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    pool.max_connections = 2
    started, release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(publish(store, monkeypatch, [[item(2)]], waiting=(started, release)))
    await asyncio.wait_for(started.wait(), 5)
    try:
        # App-token lookup + continuation each genuinely use the same constrained pool.
        response = await asyncio.wait_for(client.get("/api/user/collection", params=continuation(a, 0)), 2)
        assert response.status_code == 200 and response.json()["releases"][0]["id"] == "1"
        with pytest.raises(ProducerUnavailable, match="busy"):
            async with get_store(pool).producer(str(OTHER)):
                pytest.fail("Must reject before checkout")
        async with pool.connection() as conn:
            assert not await user_lock(conn, str(OWNER))
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    pool.max_connections = 1
    with pytest.raises(ProducerUnavailable, match=">= 2"):
        await publish(store, monkeypatch, [[item(9)]])
    response = await client.get("/api/user/collection", params=continuation(a, 0))
    assert response.status_code == 200
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT count(*) FROM user_collections WHERE release_id=9")).fetchone() == (0,)


async def test_quota_cleanup_pinned_generations_and_cross_user_serialization(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    await publish(store, monkeypatch, [[item(2)]])
    generations = get_store(pool)
    generations.limits = replace(generations.limits, generations=2)
    with pytest.raises(ProducerUnavailable, match="storage"):
        await publish(store, monkeypatch, [[item(3)]])
    assert (await client.get("/api/user/collection", params=continuation(a, 0))).status_code == 200
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE collection_generations SET retain_until=clock_timestamp()-interval '1 second' WHERE id=%s", (a["snapshot_generation"],)
        )
    await publish(store, monkeypatch, [[item(3)]])
    generations.limits = replace(generations.limits, global_rows=3, generations=8)

    # Two current generations would each consume two rows. Parallel creation
    # cannot both pass the global quota reservation under distinct user locks.
    async def create(owner: UUID) -> str:
        try:
            async with generations.producer(str(owner)) as (_conn, _generation):
                await asyncio.sleep(0.05)
            return "created"
        except ProducerUnavailable:
            return "rejected"

    results = await asyncio.gather(create(OWNER), create(OTHER))
    async with pool.connection() as conn:
        rows = await (await conn.execute("SELECT sum(total+1) FROM collection_generations")).fetchone()
    assert rows[0] <= 3 and "rejected" in results


async def test_ten_thousand_exact_membership_and_page_timings(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, _pool, client, *_ = store
    pages = [[item(i) for i in range(start, start + 100)] for start in range(1, 10001, 100)]
    start = time.perf_counter()
    await publish(store, monkeypatch, pages)
    publish_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    a = await first(client, 200)
    first_ms = (time.perf_counter() - start) * 1000
    rows = a["releases"][:]
    times = []
    for offset in range(200, 10000, 200):
        start = time.perf_counter()
        response = await client.get("/api/user/collection", params=continuation(a, offset, 200))
        times.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10000 and data["snapshot_generation"] == a["snapshot_generation"]
        rows.extend(data["releases"])
    assert [(r["id"], r["instance_id"]) for r in rows] == [(str(i), i) for i in range(1, 10001)]
    print(json.dumps({"items": len(rows), "publish_ms": publish_ms, "first_page_ms": first_ms, "continuation_p95_ms": sorted(times)[46]}))


async def test_null_zero_multiple_instances_repeat_and_reconcile(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, _pool, client, *_ = store
    missing = item(42)
    missing["instance_id"] = None
    await publish(store, monkeypatch, [[missing, item(42, 0), item(42, 2)], [missing]])
    a = await first(client, 200)
    assert [(r["id"], r["instance_id"]) for r in a["releases"]] == [("42", 0), ("42", 2), ("42", None)]
    async with driver.session() as session:
        records = await (
            await session.run("MATCH (:User{id:$owner})-[c:COLLECTED]->(:Release{id:'42'}) RETURN c.instance_id AS id ORDER BY id", owner=str(OWNER))
        ).data()
    assert {r["id"] for r in records} == {"0", "2", "legacy-no-instance"}
    await publish(store, monkeypatch, [[item(42, 2)]])
    b = await first(client, 200)
    assert [(r["id"], r["instance_id"]) for r in b["releases"]] == [("42", 2)]
    async with driver.session() as session:
        records = await (
            await session.run("MATCH (:User{id:$owner})-[c:COLLECTED]->(:Release{id:'42'}) RETURN c.instance_id AS id", owner=str(OWNER))
        ).data()
    assert records == [{"id": "2"}]


@pytest.mark.parametrize("limit", ["items", "bytes", "global_bytes"])
async def test_actual_page_capacity_rolls_back_live_and_stage_writes(store: Any, monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    generations = get_store(pool)
    bound = 1 if limit == "items" else 256
    if limit == "global_bytes":
        async with pool.connection() as conn:
            baseline = await (await conn.execute("SELECT sum(payload_bytes) FROM collection_generations")).fetchone()
        bound = int(baseline[0]) + 256 + 1  # Building metadata fits; returned page must exceed reservation.
    generations.limits = replace(generations.limits, **{limit: bound})
    captured = []
    real_stage = generations.stage

    async def record_stage(conn: Any, generation: UUID, rows: list[dict[str, Any]]) -> None:
        assert await (await conn.execute("SELECT status FROM collection_generations WHERE id=%s", (generation,))).fetchone() == ("building",)
        captured.extend(row["release_id"] for row in rows)
        await real_stage(conn, generation, rows)

    monkeypatch.setattr(generations, "stage", record_stage)
    with pytest.raises(ProducerUnavailable, match="storage"):
        await publish(store, monkeypatch, [[item(7), item(8)]])
    assert captured == [7, 8]  # Actual upsert RETURNING ran before capacity rollback.
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT count(*) FROM user_collections WHERE release_id IN (7,8)")).fetchone() == (0,)
    assert (await client.get("/api/user/collection", params=continuation(a, 0))).json()["releases"][0]["id"] == "1"


async def test_lease_publication_cleanup_race(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    generations = get_store(pool)
    # Force both issuance and next producer to contend on the real global lock.
    # Publication may win or lose; whichever generation is returned must remain pinned.
    async with pool.connection() as blocker, transaction(blocker):
        await generations.global_lock(blocker)
        issuer = asyncio.create_task(first(client, 200))
        publisher = asyncio.create_task(publish(store, monkeypatch, [[item(2)]]))
        await asyncio.sleep(0.1)
        assert not issuer.done() and not publisher.done()
    a, _count = await asyncio.gather(issuer, publisher)
    await first(client, 200)  # bounded cleanup after publication
    b = await client.get("/api/user/collection", params=continuation(a, 0, 200))
    assert b.status_code == 200 and b.json()["releases"] == a["releases"]
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT retain_until FROM collection_generations WHERE id=%s", (a["snapshot_generation"],))).fetchone()
    assert row is not None and row[0] >= datetime.fromisoformat(a["snapshot_expires_at"].replace("Z", "+00:00"))


async def test_real_min_one_pool_preflight_preserves_published_pages(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, _pool, client, tokens, params = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    small = AsyncPostgreSQLPool(params, min_connections=1, max_connections=1)
    await small.initialize()
    try:
        dependencies.configure(SECRET, pool=small)
        app_tokens.configure(small)
        user.configure(driver, SECRET, small)
        with pytest.raises(ProducerUnavailable, match=">= 2"):
            await publish((driver, small, client, tokens, params), monkeypatch, [[item(9)]])
        response = await asyncio.wait_for(client.get("/api/user/collection", params=continuation(a, 0)), 2)
        assert response.status_code == 200 and response.json()["releases"] == a["releases"]
        async with small.connection() as conn:
            assert await (await conn.execute("SELECT count(*) FROM user_collections WHERE release_id=9")).fetchone() == (0,)
        if app_tokens._background_tasks:
            await asyncio.gather(*tuple(app_tokens._background_tasks))
        assert small.active_connections == 1
    finally:
        await small.close()


async def test_completed_collection_survives_failed_wantlist(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, pool, client, *_ = store
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO oauth_tokens(user_id,provider,access_token,access_secret,provider_username) VALUES(%s,'discogs','synthetic','synthetic','synthetic')",
            (OWNER,),
        )
        await conn.execute("INSERT INTO app_config(key,value) VALUES('discogs_consumer_key','synthetic'),('discogs_consumer_secret','synthetic')")
        row = await (
            await conn.execute("INSERT INTO sync_history(user_id,sync_type,status) VALUES(%s,'full','running') RETURNING id", (OWNER,))
        ).fetchone()
    async with driver.session() as session:
        await (await session.run("CREATE(:Release{id:'7'})")).consume()
    real = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        if "/wants" in request.url.path:
            return httpx.Response(503)
        return httpx.Response(200, json={"releases": [item(7)], "pagination": {"pages": 1}})

    with monkeypatch.context() as patch:
        patch.setattr(syncer.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(respond), **kwargs))
        result = await syncer.run_full_sync(OWNER, str(row[0]), pool, driver, "synthetic")
    assert result["status"] == "failed" and result["collection_count"] == 1
    a = await first(client, 200)
    assert a["total"] == 1 and a["releases"][0]["id"] == "7"
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT status FROM sync_history WHERE id=%s", (row[0],))).fetchone() == ("failed",)


async def test_jwt_scope_revocation_and_snapshot_token_is_not_auth(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, tokens, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    body = b64url_encode(json.dumps({"sub": str(OWNER), "exp": time.time() + 300}).encode())
    header = b64url_encode(b'{"alg":"HS256","typ":"JWT"}')
    signature = b64url_encode(hmac.new(SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    client.headers["Authorization"] = f"Bearer {header}.{body}.{signature}"
    a = await first(client)
    client.headers["Authorization"] = "Bearer " + a["snapshot_token"]
    assert (await client.get("/api/user/collection", params={"snapshot": "new"})).status_code == 401
    client.headers["Authorization"] = "Bearer " + tokens[0]
    async with pool.connection() as conn:
        await conn.execute("UPDATE app_tokens SET scope=%s WHERE user_id=%s", (["other:read"], OWNER))
    assert (await client.get("/api/user/collection", params={"snapshot": "new"})).status_code == 403
    async with pool.connection() as conn:
        await conn.execute("UPDATE app_tokens SET revoked_at=clock_timestamp() WHERE user_id=%s", (OWNER,))
    assert (await client.get("/api/user/collection", params=continuation(a, 0))).status_code == 401


async def test_real_access_log_encoded_duplicate_token_keys(store: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    _driver, _pool, client, tokens, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    app = FastAPI()
    app.include_router(user.router)
    config = uvicorn.Config(app, log_config=None, lifespan="off", access_log=True)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        install_snapshot_log_redaction()
        with caplog.at_level(logging.INFO):
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + tokens[0]}) as network:
                url = f"http://127.0.0.1:{port}/api/user/collection?%73napshot=discarded-secret&snapshot={a['snapshot_token']}&snapshot_generation={a['snapshot_generation']}"
                response = await network.get(url)
                assert response.status_code == 200 and response.json()["snapshot_token"] == a["snapshot_token"]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET //[?%73napshot=malformed-canary&snapshot=second-canary HTTP/1.1\r\nHost: owned\r\nConnection: close\r\n\r\n")
            await writer.drain()
            assert b"404" in await asyncio.wait_for(reader.read(), 2)
            writer.close()
            await writer.wait_closed()
        access = [r.getMessage() for r in caplog.records if r.name in {"uvicorn.access", "httpx"}]
        assert any("200" in message for message in access)
        assert all(a["snapshot_token"] not in message and "discarded-secret" not in message for message in access)
        assert all("malformed-canary" not in message and "second-canary" not in message for message in access)
        # Uvicorn normalizes the raw '[' before emitting its access target;
        # the raw malformed-LogRecord fallback is also tested independently.
        assert any("404" in message and "REDACTED" in message for message in access)
        monkeypatch.setenv("DGS_PERF_COLLECTION_TOKEN", tokens[0])

        def actual_performance() -> list[dict[str, Any]]:
            with httpx.Client(timeout=5) as network:
                return run_collection_snapshot_perf(network, f"http://127.0.0.1:{port}", {}, 2)

        measured = await asyncio.to_thread(actual_performance)
        assert all(case["errors"] == 0 and case["iterations"] == 2 for case in measured)
        report = json.dumps(measured)
        assert tokens[0] not in report and a["snapshot_token"] not in report

    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


@pytest.mark.parametrize("store", ["legacy"], indirect=True)
async def test_existing_installation_real_schema_upgrade_preserves_live_rows(store: Any) -> None:
    _driver, pool, client, *_ = store
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT to_regclass('collection_generations')")).fetchone() == (None,)
        await conn.execute(
            "INSERT INTO user_collections(user_id,release_id,instance_id,title,label,metadata) VALUES(%s,42,99,'Legacy','Unproven','{\"catalog_number\":\"OLD\"}')",
            (OWNER,),
        )
        before = await (await conn.execute("SELECT release_id,instance_id,title,label,metadata FROM user_collections")).fetchall()
    assert await create_postgres_schema(pool) == 0
    assert await create_postgres_schema(pool) == 0
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT release_id,instance_id,title,label,metadata FROM user_collections")).fetchall() == before
        assert await (await conn.execute("SELECT count(*) FROM collection_generations")).fetchone() == (0,)
        assert await (await conn.execute("SELECT count(*) FROM collection_current")).fetchone() == (0,)
    response = await client.get("/api/user/collection", params={"snapshot": "new"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "snapshot_unavailable"


async def test_cancel_after_committed_page_never_publishes_or_leaks_lock(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    started, release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(publish(store, monkeypatch, [[item(7)], [item(8)]], waiting=(started, release, 2)))
    await asyncio.wait_for(started.wait(), 5)
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT count(*) FROM user_collections WHERE release_id=7")).fetchone() == (1,)
        assert await (
            await conn.execute(
                "SELECT count(*) FROM collection_generation_items i JOIN collection_generations g ON g.id=i.generation_id WHERE g.status='building'"
            )
        ).fetchone() == (1,)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with pool.connection() as conn:
        assert await user_lock(conn, str(OWNER))
        await release_user_lock(conn, str(OWNER))
    assert get_store(pool)._active == 0
    assert (await first(client))["snapshot_generation"] == a["snapshot_generation"]


async def test_actual_neo_reconciliation_error_after_pg_delete_keeps_previous_generation(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    real_session = driver.session

    @asynccontextmanager
    async def failing_session() -> AsyncIterator[Any]:
        async with real_session() as session:

            class Forwarded:
                async def run(self, cypher: str, *args: Any, **kwargs: Any) -> Any:
                    if "WHERE c.synced_at <" in cypher:
                        return await session.run("RETURN undefined_reconciliation_variable")
                    return await session.run(cypher, *args, **kwargs)

            yield Forwarded()

    with monkeypatch.context() as patch:
        patch.setattr(driver, "session", failing_session)
        with pytest.raises(Exception, match="undefined_reconciliation_variable"):
            await publish(store, patch, [[item(7)]])
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT release_id FROM user_collections ORDER BY release_id")).fetchall() == [(7,)]
    assert (await first(client))["snapshot_generation"] == a["snapshot_generation"]


async def test_owner_pointer_foreign_key_rejects_cross_user_generation(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    a = await first(client)
    async with pool.connection() as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await conn.execute("INSERT INTO collection_current(user_id,generation_id) VALUES(%s,%s)", (OTHER, a["snapshot_generation"]))


async def test_short_lease_begins_after_blocked_issuance_and_never_renews(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _driver, pool, client, *_ = store
    await publish(store, monkeypatch, [[item(1)]])
    generations = get_store(pool)
    generations.limits = replace(generations.limits, ttl_seconds=1)
    async with pool.connection() as blocker, transaction(blocker):
        await generations.global_lock(blocker)
        request = asyncio.create_task(first(client, 200))
        await asyncio.sleep(1.1)
        assert not request.done()
    a = await request
    assert datetime.fromisoformat(a["snapshot_expires_at"].replace("Z", "+00:00")) > datetime.now(UTC)
    immediate = await client.get("/api/user/collection", params=continuation(a, 0))
    assert immediate.status_code == 200 and immediate.json()["snapshot_expires_at"] == a["snapshot_expires_at"]
    await asyncio.sleep(1.1)
    expired = await client.get("/api/user/collection", params=continuation(a, 0))
    assert expired.status_code == 410 and expired.json()["detail"]["code"] == "snapshot_expired"
