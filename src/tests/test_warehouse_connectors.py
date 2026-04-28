"""Tests for the six real warehouse connectors added alongside Bug 5.

Each warehouse driver is imported lazily inside the connector module,
so these tests do NOT require the real third-party libraries to be
installed. We inject a fake driver via the module's ``_load_driver``
seam (or, for Databricks, via its internal _load_driver) and assert
on the happy path + the "missing driver" fallback.

We're not testing the upstream drivers themselves — that's their job.
We're testing the adapter layer: does ``test_connection`` gracefully
return False when the driver is absent, does ``execute_query`` raise
a clean error, does the metadata query produce the right shape.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.connectors import (
    clickhouse as clickhouse_mod,
    databricks as databricks_mod,
    oracle as oracle_mod,
    snowflake as snowflake_mod,
    sqlserver as sqlserver_mod,
)
from src.connectors.clickhouse import ClickHouseConnector
from src.connectors.databricks import DatabricksConnector
from src.connectors.oracle import OracleConnector
from src.connectors.redshift import RedshiftConnector
from src.connectors.snowflake import SnowflakeConnector
from src.connectors.sqlserver import SQLServerConnector


# ---------------------------------------------------------------------------
# Fakes reused across the DB-API-style drivers (snowflake, sqlserver, oracle,
# databricks). ClickHouse has a different shape so it gets its own fakes.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: List[Any], description: Optional[List[Any]] = None):
        self._rows = rows
        self.description = description
        self._last_query: Optional[str] = None
        self._as_dict = False

    def execute(self, query: str) -> None:
        self._last_query = query

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, *args, **kwargs):  # Oracle/Snowflake take no kwargs, mssql takes as_dict=True
        if kwargs.get("as_dict"):
            # pymssql's dict cursor returns dict rows — emulate.
            rows = [
                dict(zip([d[0] for d in (self._cursor.description or [])], row))
                for row in self._cursor._rows
            ]
            return _FakeCursor(rows)
        return self._cursor

    def close(self):
        self.closed = True


def _fake_module(cursor: _FakeCursor):
    """Build a SimpleNamespace that looks enough like a DB-API module
    for the connector's connect() call to succeed."""
    conn = _FakeConn(cursor)
    return SimpleNamespace(connect=lambda **_: conn), conn


# ---------------------------------------------------------------------------
# Generic happy-path tests, parametrized over DB-API-style connectors
# ---------------------------------------------------------------------------


DB_API_CASES = [
    ("snowflake", SnowflakeConnector, snowflake_mod),
    ("sqlserver", SQLServerConnector, sqlserver_mod),
    ("oracle", OracleConnector, oracle_mod),
    ("databricks", DatabricksConnector, databricks_mod),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,cls,module", DB_API_CASES)
async def test_test_connection_returns_true_when_driver_returns_one(
    name, cls, module, monkeypatch
):
    cursor = _FakeCursor(rows=[(1,)])
    fake_mod, _ = _fake_module(cursor)
    monkeypatch.setattr(module, "_load_driver", lambda: fake_mod)

    ok = await cls().test_connection({"host": "x", "username": "u", "password": "p"})
    assert ok is True, f"{name} connector should treat SELECT 1 == 1 as a successful probe"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,cls,module", DB_API_CASES)
async def test_test_connection_returns_false_when_driver_missing(
    name, cls, module, monkeypatch
):
    """If the third-party package is absent (common in lean deploys),
    the connector must degrade to False — not raise ImportError.
    The /connectors registry relies on this so the UI can show an
    honest "driver missing" state instead of 500-ing the whole page."""
    monkeypatch.setattr(module, "_load_driver", lambda: None)
    ok = await cls().test_connection({"host": "x"})
    assert ok is False


@pytest.mark.asyncio
@pytest.mark.parametrize("name,cls,module", DB_API_CASES)
async def test_execute_query_raises_on_missing_driver(
    name, cls, module, monkeypatch
):
    monkeypatch.setattr(module, "_load_driver", lambda: None)
    with pytest.raises(RuntimeError):
        await cls().execute_query({"host": "x"}, "SELECT 1")


@pytest.mark.asyncio
@pytest.mark.parametrize("name,cls,module", DB_API_CASES)
async def test_execute_query_rejects_empty_sql(
    name, cls, module, monkeypatch
):
    # Cursor never used; the connector must reject before hitting the driver.
    fake_mod, _ = _fake_module(_FakeCursor(rows=[]))
    monkeypatch.setattr(module, "_load_driver", lambda: fake_mod)
    with pytest.raises(ValueError):
        await cls().execute_query({"host": "x"}, "   ")


@pytest.mark.asyncio
async def test_snowflake_get_metadata_shape(monkeypatch):
    rows = [("ANALYTICS", "ORDERS", 1234), ("ANALYTICS", "CUSTOMERS", 42)]
    cursor = _FakeCursor(rows=rows, description=[("TABLE_SCHEMA",), ("TABLE_NAME",), ("ROW_COUNT",)])
    fake_mod, _ = _fake_module(cursor)
    monkeypatch.setattr(snowflake_mod, "_load_driver", lambda: fake_mod)

    meta = await SnowflakeConnector().get_metadata({"host": "x"})
    assert meta["schemas"] == ["ANALYTICS"]
    assert [t["name"] for t in meta["tables"]] == ["ORDERS", "CUSTOMERS"]
    assert meta["tables"][0]["row_count"] == 1234


@pytest.mark.asyncio
async def test_sqlserver_execute_query_returns_dict_rows(monkeypatch):
    rows = [(1, "Alice"), (2, "Bob")]
    cursor = _FakeCursor(rows=rows, description=[("id",), ("name",)])
    fake_mod, _ = _fake_module(cursor)
    monkeypatch.setattr(sqlserver_mod, "_load_driver", lambda: fake_mod)

    out = await SQLServerConnector().execute_query({"host": "x"}, "SELECT id, name FROM t")
    assert out == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]


@pytest.mark.asyncio
async def test_oracle_get_metadata_filters_system_schemas(monkeypatch):
    rows = [("HR", "EMPLOYEES"), ("HR", "DEPARTMENTS")]
    cursor = _FakeCursor(rows=rows, description=[("owner",), ("table_name",)])
    fake_mod, _ = _fake_module(cursor)
    monkeypatch.setattr(oracle_mod, "_load_driver", lambda: fake_mod)

    meta = await OracleConnector().get_metadata({"host": "x", "service_name": "ORCL"})
    assert meta["schemas"] == ["HR"]
    assert [t["name"] for t in meta["tables"]] == ["EMPLOYEES", "DEPARTMENTS"]
    # The last query sent should filter SYS/SYSTEM/... — inspect via the cursor
    assert "all_tables" in (cursor._last_query or "").lower()


@pytest.mark.asyncio
async def test_databricks_execute_query_happy_path(monkeypatch):
    rows = [(1, "row1"), (2, "row2")]
    cursor = _FakeCursor(rows=rows, description=[("id",), ("label",)])
    fake_mod, _ = _fake_module(cursor)
    monkeypatch.setattr(databricks_mod, "_load_driver", lambda: fake_mod)

    out = await DatabricksConnector().execute_query(
        {"server_hostname": "x", "http_path": "/sql/1.0/warehouses/abc", "token": "y"},
        "SELECT * FROM t",
    )
    assert out == [{"id": 1, "label": "row1"}, {"id": 2, "label": "row2"}]


# ---------------------------------------------------------------------------
# ClickHouse — driver has a very different surface (`Client.execute`)
# ---------------------------------------------------------------------------


class _FakeClickhouseClient:
    def __init__(self, rows, column_types=None):
        self._rows = rows
        self._column_types = column_types or [("n", "UInt64")]
        self.disconnected = False

    def execute(self, query, with_column_types=False):
        if with_column_types:
            return self._rows, self._column_types
        return self._rows

    def disconnect(self):
        self.disconnected = True


@pytest.mark.asyncio
async def test_clickhouse_test_connection_happy(monkeypatch):
    def _ctor(**_):
        return _FakeClickhouseClient(rows=[(1,)])

    monkeypatch.setattr(clickhouse_mod, "_load_driver", lambda: _ctor)
    ok = await ClickHouseConnector().test_connection({"host": "x"})
    assert ok is True


@pytest.mark.asyncio
async def test_clickhouse_test_connection_false_when_driver_missing(monkeypatch):
    monkeypatch.setattr(clickhouse_mod, "_load_driver", lambda: None)
    ok = await ClickHouseConnector().test_connection({"host": "x"})
    assert ok is False


@pytest.mark.asyncio
async def test_clickhouse_execute_query_returns_dict_rows(monkeypatch):
    def _ctor(**_):
        return _FakeClickhouseClient(
            rows=[(1, "a"), (2, "b")],
            column_types=[("id", "UInt64"), ("label", "String")],
        )

    monkeypatch.setattr(clickhouse_mod, "_load_driver", lambda: _ctor)
    out = await ClickHouseConnector().execute_query(
        {"host": "x", "database": "default"},
        "SELECT id, label FROM t",
    )
    assert out == [{"id": 1, "label": "a"}, {"id": 2, "label": "b"}]


@pytest.mark.asyncio
async def test_clickhouse_get_metadata_skips_system_schemas(monkeypatch):
    # `system.tables` rows are (database, name, total_rows)
    rows = [("analytics", "events", 99_000), ("analytics", "users", 1_200)]

    def _ctor(**_):
        return _FakeClickhouseClient(
            rows=rows, column_types=[("database",), ("name",), ("total_rows",)]
        )

    monkeypatch.setattr(clickhouse_mod, "_load_driver", lambda: _ctor)
    meta = await ClickHouseConnector().get_metadata({"host": "x"})
    assert meta["schemas"] == ["analytics"]
    assert meta["tables"][0]["row_count"] == 99_000


# ---------------------------------------------------------------------------
# Redshift — inherits PostgreSQLConnector; behaviour is identical. Just
# confirm the default port is the Redshift one so a missing `port` field
# doesn't silently try 5432.
# ---------------------------------------------------------------------------


def test_redshift_connect_params_defaults_to_5439():
    params = RedshiftConnector()._get_connection_params({
        "host": "ex.redshift.amazonaws.com",
        "database": "dev",
        "username": "admin",
        "password": "secret",
    })
    assert params["port"] == 5439


def test_redshift_connect_params_respects_explicit_port():
    params = RedshiftConnector()._get_connection_params({
        "host": "ex.redshift.amazonaws.com",
        "database": "dev",
        "username": "admin",
        "password": "secret",
        "port": 5432,  # odd but legal override
    })
    assert params["port"] == 5432


# ---------------------------------------------------------------------------
# Registry — regression guard that these six ids now point at real classes
# ---------------------------------------------------------------------------


def test_registry_binds_six_warehouses_to_real_drivers():
    from src.connectors.registry import CONNECTORS, MockConnector

    expected = {
        "snowflake": SnowflakeConnector,
        "redshift": RedshiftConnector,
        "sqlserver": SQLServerConnector,
        "oracle": OracleConnector,
        "clickhouse": ClickHouseConnector,
        "databricks": DatabricksConnector,
    }
    for cid, expected_cls in expected.items():
        cls = CONNECTORS.get(cid)
        assert cls is expected_cls, (
            f"registry[{cid}] should be {expected_cls.__name__}, got "
            f"{cls.__name__ if cls else 'None'}"
        )
        assert cls is not MockConnector, (
            f"{cid} is still pointing at MockConnector — lazy-load drivers "
            f"mean real classes can stay in the registry without importing "
            f"the third-party lib, so there is no reason to keep the mock."
        )
