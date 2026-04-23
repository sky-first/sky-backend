"""Databricks SQL Warehouse connector.

Uses ``databricks-sql-connector`` (the official driver for Databricks
SQL Warehouses / endpoints). Driver is sync, so calls are dispatched
via ``asyncio.to_thread``. Imported lazily.

Config::

    {
        "server_hostname": "adb-12345.6.azuredatabricks.net",
        "http_path": "/sql/1.0/warehouses/abc12345",
        "token": "dapi***",
        "database": "main",           # optional catalog/database
    }
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _load_driver():
    try:
        from databricks import sql  # type: ignore

        return sql
    except Exception as exc:  # pragma: no cover - import error path
        logger.info("databricks-sql-connector not available: %s", exc)
        return None


def _connect_kwargs(config: Dict[str, Any]) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "server_hostname": config.get("server_hostname") or config.get("host"),
        "http_path": config.get("http_path"),
        "access_token": config.get("token") or config.get("access_token"),
    }
    # ``catalog`` and ``schema`` are optional but cheap to forward when set.
    if config.get("catalog"):
        kwargs["catalog"] = config["catalog"]
    if config.get("database") or config.get("schema"):
        kwargs["schema"] = config.get("schema") or config.get("database")
    return kwargs


class DatabricksConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        drv = _load_driver()
        if drv is None:
            return False

        def _probe() -> bool:
            try:
                conn = drv.connect(**_connect_kwargs(config))
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    row = cur.fetchone()
                    return bool(row and row[0] == 1)
                finally:
                    conn.close()
            except Exception as exc:
                logger.info("Databricks test_connection failed: %s", exc)
                return False

        return await asyncio.to_thread(_probe)

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        drv = _load_driver()
        if drv is None:
            return {"tables": [], "schemas": []}

        def _probe() -> Dict[str, Any]:
            try:
                conn = drv.connect(**_connect_kwargs(config))
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT table_schema, table_name "
                        "FROM information_schema.tables "
                        "WHERE table_type = 'BASE TABLE' "
                        "ORDER BY table_schema, table_name"
                    )
                    rows = cur.fetchall() or []
                    schemas: List[str] = []
                    tables: List[Dict[str, Any]] = []
                    seen: set = set()
                    for schema, name in rows:
                        if schema not in seen:
                            schemas.append(schema)
                            seen.add(schema)
                        tables.append({
                            "name": name,
                            "schema": schema,
                            "columns": [],
                        })
                    return {"tables": tables, "schemas": schemas}
                finally:
                    conn.close()
            except Exception as exc:
                logger.warning("Databricks get_metadata failed: %s", exc)
                return {"tables": [], "schemas": []}

        return await asyncio.to_thread(_probe)

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        drv = _load_driver()
        if drv is None:
            raise RuntimeError("databricks-sql-connector not installed")
        if not (query or "").strip():
            raise ValueError("Databricks execute_query requires a SQL statement")

        def _run() -> List[Dict[str, Any]]:
            conn = drv.connect(**_connect_kwargs(config))
            try:
                cur = conn.cursor()
                cur.execute(query)
                cols = [c[0] for c in (cur.description or [])]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        meta = await self.get_metadata(config)
        rows_by_table: Dict[str, int] = {}
        for t in meta.get("tables", []):
            schema = t.get("schema")
            name = t.get("name")
            if not name:
                continue
            full = f"{schema}.{name}" if schema else name
            try:
                rows = await self.execute_query(config, f"SELECT COUNT(*) AS n FROM {full}")
                rows_by_table[full] = int(rows[0].get("n", 0)) if rows else 0
            except Exception:
                rows_by_table[full] = 0
        return {"success": True, "rows_by_table": rows_by_table}
