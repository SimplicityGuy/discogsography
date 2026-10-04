"""Canonical source pairs through real producer, PostgreSQL, Neo4j and HTTP paths.

Requires explicitly owned servers via DGS_PAIRS_*; never uses ambient operator
endpoints. Run with ``-m integration -n0`` against the disposable pair servers.
"""

import asyncio
from collections.abc import AsyncIterator
import os
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi import FastAPI
import httpx
import psycopg
from psycopg import sql
import pytest
import pytest_asyncio

from api import app_tokens, dependencies, syncer
from api.app_tokens import generate_plaintext_token, hash_token
from api.queries.user_queries import get_user_collection, get_user_wantlist
from api.routers import user as user_router
from common import AsyncPostgreSQLPool, AsyncResilientNeo4jDriver
from graphinator.batch_processor import Neo4jBatchProcessor, PendingMessage
from postgres_schema import _USER_TABLES


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
USER = UUID("00000000-0000-0000-0000-000000000001")
LABELS = [{"id": "10", "name": "Label A", "catno": "A-1"}, {"id": "20", "name": "Label B", "catno": "B-2"}]


@pytest_asyncio.fixture
async def pair_store() -> AsyncIterator[tuple[AsyncResilientNeo4jDriver, AsyncPostgreSQLPool]]:
    assert os.environ.get("DGS_PAIRS_ISOLATED") == "1", "Only explicitly owned disposable servers are permitted"
    driver = AsyncResilientNeo4jDriver(os.environ["DGS_PAIRS_NEO4J_URI"], ("neo4j", os.environ["DGS_PAIRS_NEO4J_PASSWORD"]))
    parent = os.environ["DGS_PAIRS_POSTGRES_DSN"]
    name = "pairs_" + uuid4().hex
    with psycopg.connect(parent, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    pool = AsyncPostgreSQLPool({**psycopg.conninfo.conninfo_to_dict(parent), "dbname": name}, min_connections=1, max_connections=3)
    await pool.initialize()
    try:
        async with pool.connection() as conn:
            assert await (await conn.execute("SELECT current_database()")).fetchone() == (name,)
            for table, ddl in _USER_TABLES:
                if table in {"users table", "app_tokens table", "user_collections table", "user_wantlists table"}:
                    await conn.execute(ddl)
            await conn.execute("INSERT INTO users(id,email,hashed_password) VALUES (%s,'pairs@example.invalid','synthetic')", (USER,))
        async with driver.session() as session:
            await (await session.run("MATCH (n) DETACH DELETE n")).consume()
        yield driver, pool
    finally:
        await pool.close()
        async with driver.session() as session:
            await (await session.run("MATCH (n) DETACH DELETE n")).consume()
        await driver.close()
        with psycopg.connect(parent, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


async def ingest(driver: AsyncResilientNeo4jDriver, labels: Any, sha: str = "same-hash") -> None:
    data = {"id": "42", "title": "Synthetic pair", "year": 2000, "sha256": sha, "labels": labels}
    processor = Neo4jBatchProcessor(driver)
    assert await processor._process_releases_batch([PendingMessage("releases", data, AsyncMock(), AsyncMock())]) == set()


async def graph_pair(driver: AsyncResilientNeo4jDriver) -> tuple[Any, Any]:
    async with driver.session() as session:
        row = await (await session.run("MATCH (r:Release {id:'42'}) RETURN r.canonical_label AS label, r.catalog_number AS catno")).single()
    assert row is not None
    return row["label"], row["catno"]


async def collect(driver: AsyncResilientNeo4jDriver) -> None:
    async with driver.session() as session:
        await (
            await session.run(
                "MERGE (u:User {id:$user}) WITH u MATCH (r:Release {id:'42'}) MERGE (u)-[:COLLECTED {instance_id:'1',date_added:'2026-01-01'}]->(r)",
                user=str(USER),
            )
        ).consume()


async def sync_page(
    driver: AsyncResilientNeo4jDriver, pool: AsyncPostgreSQLPool, labels: Any, monkeypatch: pytest.MonkeyPatch, wantlist: bool = False
) -> None:
    item = {
        "id": 42,
        "instance_id": 1,
        "date_added": "2026-01-01T00:00:00Z",
        "basic_information": {"id": 42, "title": "Synthetic pair", "artists": [], "labels": labels},
    }
    response = {"wants" if wantlist else "releases": [item], "pagination": {"pages": 1}}
    real_client = httpx.AsyncClient
    with monkeypatch.context() as patch:
        patch.setattr(
            syncer.httpx,
            "AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response)), **kwargs),
        )
        function = syncer.sync_wantlist if wantlist else syncer.sync_collection
        assert await function(USER, "synthetic", "key", "secret", "access", "token", "test", pool, driver) == 1


async def test_graphinator_backfills_unchanged_hash_and_relationship_order_is_irrelevant(pair_store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, pool = pair_store
    async with driver.session() as session:
        await (await session.run("CREATE (:Release {id:'42', title:'Legacy', sha256:'same-hash', catalog_number:'A-1'})")).consume()
    await ingest(driver, LABELS)
    assert await graph_pair(driver) == ("Label A", "A-1")
    await collect(driver)
    async with driver.session() as session:
        await (await session.run("MATCH (r:Release {id:'42'})-[e:ON]->() DELETE e")).consume()
        for label in reversed(LABELS):
            await (await session.run("MATCH (r:Release {id:'42'}),(l:Label {id:$id}) CREATE (r)-[:ON]->(l)", id=label["id"])).consume()
    rows, total = await get_user_collection(driver, str(USER))
    assert total == len(rows) == 1
    assert (rows[0]["label"], rows[0]["catalog_number"]) == ("Label A", "A-1")
    token = generate_plaintext_token()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO app_tokens(user_id,name,scope,token_hash) VALUES (%s,'Synthetic pair proof',%s,%s)",
            (USER, ["collection:read"], hash_token(token)),
        )
    monkeypatch.setattr(app_tokens, "_pool", pool)
    monkeypatch.setattr(dependencies, "_pool", pool)
    monkeypatch.setattr(dependencies, "_jwt_secret", "synthetic-pair-secret")
    monkeypatch.setattr(user_router, "_neo4j_driver", driver)
    app = FastAPI()
    app.include_router(user_router.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        unauthenticated = await client.get("/api/user/collection")
        assert unauthenticated.status_code == 401
        response = await client.get("/api/user/collection", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        row = response.json()["releases"][0]
        assert (row["label"], row["catalog_number"]) == ("Label A", "A-1")
    if app_tokens._background_tasks:
        await asyncio.gather(*tuple(app_tokens._background_tasks))


@pytest.mark.parametrize(
    "labels,expected",
    [
        (LABELS, ("Label A", "A-1")),
        ([{"name": "New Label"}], ("New Label", None)),
        ([{"catno": "NEW-2"}], (None, "NEW-2")),
        ([], ("Old Label", "OLD-1")),
        ([{}], ("Old Label", "OLD-1")),
    ],
)
async def test_curator_pg_and_graph_apply_the_same_atomic_pair(
    pair_store: Any, monkeypatch: pytest.MonkeyPatch, labels: Any, expected: tuple[Any, Any]
) -> None:
    driver, pool = pair_store
    await ingest(driver, [{"id": "10", "name": "Old Label", "catno": "OLD-1"}])
    await sync_page(driver, pool, [{"name": "Old Label", "catno": "OLD-1"}], monkeypatch)
    await sync_page(driver, pool, labels, monkeypatch)
    assert await graph_pair(driver) == expected
    async with pool.connection() as conn:
        row = await (
            await conn.execute("SELECT label,metadata->>'catalog_number' FROM user_collections WHERE user_id=%s AND release_id=42", (USER,))
        ).fetchone()
    assert row == expected
    rows, total = await get_user_collection(driver, str(USER))
    assert total == len(rows) == 1
    assert (rows[0]["label"], rows[0]["catalog_number"]) == expected


async def test_wantlist_writer_and_query_use_the_first_source_pair(pair_store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, pool = pair_store
    await ingest(driver, LABELS)
    await sync_page(driver, pool, [{"name": "Want Label", "catno": "WANT-1"}, *LABELS], monkeypatch, wantlist=True)
    assert await graph_pair(driver) == ("Want Label", "WANT-1")
    rows, total = await get_user_wantlist(driver, str(USER))
    assert total == len(rows) == 1
    assert (rows[0]["label"], rows[0]["catalog_number"]) == ("Want Label", "WANT-1")


@pytest.mark.parametrize(
    "labels,expected", [([{"name": "New"}], ("New", None)), ([{"catno": "NEW"}], (None, "NEW")), ([], ("Old", "OLD")), ([{}], ("Old", "OLD"))]
)
async def test_graphinator_partial_sources_and_absence(pair_store: Any, labels: Any, expected: tuple[Any, Any]) -> None:
    driver, _pool = pair_store
    await ingest(driver, [{"id": "10", "name": "Old", "catno": "OLD"}])
    await ingest(driver, labels, sha="changed")
    assert await graph_pair(driver) == expected


async def test_legacy_unknown_pair_stays_unknown_and_backfill_is_not_repeated(pair_store: Any) -> None:
    driver, _pool = pair_store
    async with driver.session() as session:
        await (
            await session.run(
                "CREATE (r:Release {id:'42', title:'Legacy', sha256:'same-hash', catalog_number:'OLD'}), (l:Label {name:'Arbitrary'}), (r)-[:ON]->(l)"
            )
        ).consume()
    await collect(driver)
    rows, total = await get_user_collection(driver, str(USER))
    assert total == len(rows) == 1
    assert (rows[0]["label"], rows[0]["catalog_number"]) == (None, None)
    await ingest(driver, [])
    async with driver.session() as session:
        await (await session.run("MATCH (r:Release {id:'42'}) SET r.title='Skip sentinel'")).consume()
    await ingest(driver, [])
    async with driver.session() as session:
        row = await (
            await session.run("MATCH (r:Release {id:'42'}) RETURN r.title AS title, r.canonical_pair_version AS version, r.catalog_number AS catno")
        ).single()
    assert row is not None
    assert (row["title"], row["version"], row["catno"]) == ("Skip sentinel", 1, "OLD")


async def test_pg_pair_constraint_failure_cannot_partially_change_either_store(pair_store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, pool = pair_store
    await ingest(driver, LABELS)
    await sync_page(driver, pool, LABELS, monkeypatch)
    async with pool.connection() as conn:
        await conn.execute("ALTER TABLE user_collections ADD CONSTRAINT synthetic_label_check CHECK (label IS DISTINCT FROM 'Rejected')")
    with pytest.raises(psycopg.errors.CheckViolation):
        await sync_page(driver, pool, [{"name": "Rejected", "catno": "NEW"}], monkeypatch)
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT label,metadata->>'catalog_number' FROM user_collections WHERE release_id=42")).fetchone()
    assert row == ("Label A", "A-1")
    assert await graph_pair(driver) == ("Label A", "A-1")


async def test_curator_inspection_cannot_suppress_original_feed_backfill(pair_store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    driver, pool = pair_store
    async with driver.session() as session:
        await (await session.run("CREATE (:Release {id:'42', title:'Legacy', sha256:'same-hash', catalog_number:'OLD'})")).consume()
    await sync_page(driver, pool, [], monkeypatch)
    await ingest(driver, LABELS)
    assert await graph_pair(driver) == ("Label A", "A-1")
    rows, total = await get_user_collection(driver, str(USER))
    assert total == len(rows) == 1
    assert (rows[0]["label"], rows[0]["catalog_number"]) == ("Label A", "A-1")
