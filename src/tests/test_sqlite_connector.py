"""Tests for src/connectors/sqlite.py.

Hermetic — every test writes its own temp .sqlite file, so nothing
persists between runs and the suite stays fast.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.connectors.sqlite import SQLiteConnector


def _seed_db(path: Path) -> None:
    """Create a small sales fixture via the stdlib driver so the
    connector-under-test doesn't have to write it itself."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL)")
        conn.executemany(
            "INSERT INTO customers (id, name) VALUES (?, ?)",
            [(1, "Ada"), (2, "Bob")],
        )
        conn.executemany(
            "INSERT INTO orders (id, customer_id, total) VALUES (?, ?, ?)",
            [(1, 1, 9.99), (2, 1, 19.99), (3, 2, 4.50)],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_test_connection_true_on_existing_file():
    with TemporaryDirectory() as d:
        path = Path(d) / "db.sqlite"
        _seed_db(path)
        ok = await SQLiteConnector().test_connection({"path": str(path)})
    assert ok is True


@pytest.mark.asyncio
async def test_test_connection_false_when_path_missing():
    assert await SQLiteConnector().test_connection({}) is False


@pytest.mark.asyncio
async def test_test_connection_false_when_file_missing_and_read_only():
    ok = await SQLiteConnector().test_connection(
        {"path": "/tmp/does-not-exist.sqlite", "read_only": True}
    )
    assert ok is False


@pytest.mark.asyncio
async def test_get_metadata_lists_tables_with_columns():
    with TemporaryDirectory() as d:
        path = Path(d) / "db.sqlite"
        _seed_db(path)
        meta = await SQLiteConnector().get_metadata({"path": str(path)})
    names = {t["name"] for t in meta["tables"]}
    assert names == {"customers", "orders"}
    orders = next(t for t in meta["tables"] if t["name"] == "orders")
    # Column info comes from PRAGMA table_info.
    col_names = [c["name"] for c in orders["columns"]]
    assert col_names == ["id", "customer_id", "total"]
    assert orders["kind"] == "sqlite_table"


@pytest.mark.asyncio
async def test_get_metadata_excludes_internal_sqlite_tables():
    with TemporaryDirectory() as d:
        path = Path(d) / "db.sqlite"
        _seed_db(path)
        # sqlite_master is automatically there; the connector filters
        # `sqlite_%` so it shouldn't surface.
        meta = await SQLiteConnector().get_metadata({"path": str(path)})
    names = [t["name"] for t in meta["tables"]]
    assert all(not n.startswith("sqlite_") for n in names)


@pytest.mark.asyncio
async def test_execute_query_returns_dict_rows():
    with TemporaryDirectory() as d:
        path = Path(d) / "db.sqlite"
        _seed_db(path)
        rows = await SQLiteConnector().execute_query(
            {"path": str(path)},
            "SELECT id, name FROM customers ORDER BY id",
        )
    assert rows == [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Bob"},
    ]


@pytest.mark.asyncio
async def test_execute_query_read_only_blocks_writes():
    """Default read_only=True must prevent destructive SQL — even an
    agent with a buggy prompt can't drop a table."""
    with TemporaryDirectory() as d:
        path = Path(d) / "db.sqlite"
        _seed_db(path)
        with pytest.raises(Exception):
            await SQLiteConnector().execute_query(
                {"path": str(path), "read_only": True},
                "DELETE FROM customers",
            )
        # The file is untouched.
        fresh = await SQLiteConnector().execute_query(
            {"path": str(path)},
            "SELECT COUNT(*) AS n FROM customers",
        )
        assert fresh[0]["n"] == 2


@pytest.mark.asyncio
async def test_execute_query_read_write_mode_allows_writes():
    """Explicit read_only=False lets the connector write — used by
    test fixtures / migrations, not by agent runs."""
    with TemporaryDirectory() as d:
        path = Path(d) / "db.sqlite"
        _seed_db(path)
        await SQLiteConnector().execute_query(
            {"path": str(path), "read_only": False},
            "INSERT INTO customers (id, name) VALUES (3, 'Carol')",
        )
        rows = await SQLiteConnector().execute_query(
            {"path": str(path)},
            "SELECT COUNT(*) AS n FROM customers",
        )
    assert rows[0]["n"] == 3


@pytest.mark.asyncio
async def test_execute_query_rejects_empty_sql():
    with pytest.raises(ValueError, match="SQL statement"):
        await SQLiteConnector().execute_query({"path": "/tmp/x.sqlite"}, "")


@pytest.mark.asyncio
async def test_execute_query_rejects_missing_path():
    with pytest.raises(ValueError, match="path"):
        await SQLiteConnector().execute_query({}, "SELECT 1")


@pytest.mark.asyncio
async def test_sync_data_counts_rows_by_table():
    with TemporaryDirectory() as d:
        path = Path(d) / "db.sqlite"
        _seed_db(path)
        out = await SQLiteConnector().sync_data({"path": str(path)})
    assert out["success"] is True
    assert out["rows_by_table"] == {"customers": 2, "orders": 3}
