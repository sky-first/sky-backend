"""Tests for src/connectors/mongodb.py.

We don't spin up a real mongod; every pymongo call is mocked via
the module-level MongoClient import. Keeps the suite hermetic and
fast (~30ms).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.mongodb import MongoDBConnector


class _FakeClient:
    def __init__(self, collections=None, docs=None, raise_on_ping=False, aggregate_docs=None):
        self._collections = collections or {}
        self._docs = docs or []
        self._raise = raise_on_ping
        self._aggregate_docs = aggregate_docs or []
        self.admin = MagicMock()
        self.admin.command = MagicMock(side_effect=self._ping)
        self.closed = False

    def _ping(self, *args, **kwargs):
        if self._raise:
            from pymongo.errors import PyMongoError
            raise PyMongoError("boom")
        return {"ok": 1}

    def __getitem__(self, db_name):
        db = MagicMock()
        db.list_collection_names = MagicMock(return_value=list(self._collections.keys()))

        def get_coll(name):
            coll = MagicMock()
            cursor = MagicMock()

            def find(filter_, projection=None):
                cursor._filter = filter_
                cursor._projection = projection
                cursor._data = list(self._docs)
                cursor.limit = MagicMock(side_effect=lambda n: _ListCursor(cursor._data[:n]))
                return cursor

            coll.find = MagicMock(side_effect=find)
            coll.aggregate = MagicMock(return_value=iter(self._aggregate_docs))
            return coll

        db.__getitem__ = MagicMock(side_effect=get_coll)
        return db

    def close(self):
        self.closed = True


class _ListCursor(list):
    def __iter__(self):
        return iter(list.__iter__(self))


@pytest.mark.asyncio
async def test_test_connection_true_when_ping_succeeds():
    fake = _FakeClient()
    with patch("src.connectors.mongodb.MongoClient", return_value=fake):
        ok = await MongoDBConnector().test_connection({"uri": "mongodb://x:27017"})
    assert ok is True
    assert fake.closed is True  # client got closed


@pytest.mark.asyncio
async def test_test_connection_false_when_ping_raises():
    fake = _FakeClient(raise_on_ping=True)
    with patch("src.connectors.mongodb.MongoClient", return_value=fake):
        ok = await MongoDBConnector().test_connection({"uri": "mongodb://x:27017"})
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_false_without_uri():
    ok = await MongoDBConnector().test_connection({})
    assert ok is False


@pytest.mark.asyncio
async def test_execute_query_plain_string_lists_top_n_docs():
    docs = [
        {"_id": "abc", "name": "Ada", "price": 10},
        {"_id": "def", "name": "Bob", "price": 20},
    ]
    fake = _FakeClient(docs=docs)
    with patch("src.connectors.mongodb.MongoClient", return_value=fake):
        rows = await MongoDBConnector().execute_query(
            {"uri": "mongodb://x:27017", "database": "mydb"},
            "orders",
        )
    assert len(rows) == 2
    assert rows[0]["_id"] == "abc"  # stringified
    assert rows[0]["name"] == "Ada"


@pytest.mark.asyncio
async def test_execute_query_normalizes_datetime_to_isoformat():
    docs = [{"_id": "x", "created_at": datetime(2026, 4, 23, tzinfo=timezone.utc)}]
    fake = _FakeClient(docs=docs)
    with patch("src.connectors.mongodb.MongoClient", return_value=fake):
        rows = await MongoDBConnector().execute_query(
            {"uri": "mongodb://x:27017", "database": "mydb"}, "items"
        )
    assert rows[0]["created_at"] == "2026-04-23T00:00:00+00:00"


@pytest.mark.asyncio
async def test_execute_query_json_descriptor_honors_limit_and_filter():
    docs = [{"_id": f"{i}", "n": i} for i in range(20)]
    fake = _FakeClient(docs=docs)
    with patch("src.connectors.mongodb.MongoClient", return_value=fake):
        rows = await MongoDBConnector().execute_query(
            {"uri": "mongodb://x:27017", "database": "mydb"},
            '{"collection":"events","filter":{"status":"open"},"limit":5}',
        )
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_execute_query_aggregate_pipeline_returns_pipeline_docs():
    agg_docs = [{"_id": "A", "count": 3}, {"_id": "B", "count": 1}]
    fake = _FakeClient(aggregate_docs=agg_docs)
    with patch("src.connectors.mongodb.MongoClient", return_value=fake):
        rows = await MongoDBConnector().execute_query(
            {"uri": "mongodb://x:27017", "database": "mydb"},
            '{"collection":"orders","pipeline":[{"$group":{"_id":"$region","count":{"$sum":1}}}]}',
        )
    assert rows == [{"_id": "A", "count": 3}, {"_id": "B", "count": 1}]


@pytest.mark.asyncio
async def test_execute_query_rejects_missing_database():
    with pytest.raises(ValueError, match="database"):
        await MongoDBConnector().execute_query({"uri": "mongodb://x:27017"}, "orders")


@pytest.mark.asyncio
async def test_execute_query_rejects_empty_query():
    with pytest.raises(ValueError):
        await MongoDBConnector().execute_query(
            {"uri": "mongodb://x:27017", "database": "db"}, ""
        )


@pytest.mark.asyncio
async def test_get_metadata_lists_declared_collections():
    meta = await MongoDBConnector().get_metadata({
        "uri": "mongodb://x:27017",
        "database": "mydb",
        "collections": [
            {"name": "orders", "collection": "orders"},
            {"name": "customers", "collection": "customers", "filter": {"active": True}},
        ],
    })
    names = [t["name"] for t in meta["tables"]]
    assert names == ["orders", "customers"]
    assert meta["tables"][0]["kind"] == "mongo_collection"
    assert meta["tables"][1]["metadata"]["filter"] == {"active": True}
