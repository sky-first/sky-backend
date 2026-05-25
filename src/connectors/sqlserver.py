"""Microsoft SQL Server connector.

Uses ``pymssql`` (pure Python, no ODBC) so deployment doesn't need an
OS-level driver package. The driver is synchronous, so calls are
dispatched via ``asyncio.to_thread``. Imported lazily so the app can
still boot when the optional dep is missing.

Config::

    {
        "host": "sqlserver.internal",
        "port": 1433,
        "database": "sales",
        "username": "sa",
        "password": "***",
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
        import pymssql  # type: ignore

        return pymssql
    except Exception as exc:  # pragma: no cover - import error path
        logger.info("pymssql driver not available: %s", exc)
        return None


def _connect_params(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "server": config.get("host"),
        "port": int(config.get("port") or 1433),
        "user": config.get("username") or config.get("user"),
        "password": config.get("password"),
        "database": config.get("database"),
        "timeout": int(config.get("timeout", 10)),
    }


class SQLServerConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        drv = _load_driver()
        if drv is None:
            return False

        def _probe() -> bool:
            try:
                conn = drv.connect(**_connect_params(config))
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    row = cur.fetchone()
                    return bool(row and row[0] == 1)
                finally:
                    conn.close()
            except Exception as exc:
                logger.info("SQLServer test_connection failed: %s", exc)
                return False

        return await asyncio.to_thread(_probe)

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        drv = _load_driver()
        if drv is None:
            return {"tables": [], "schemas": []}

        def _probe() -> Dict[str, Any]:
            try:
                conn = drv.connect(**_connect_params(config))
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT TABLE_SCHEMA, TABLE_NAME "
                        "FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_TYPE = 'BASE TABLE' "
                        "ORDER BY TABLE_SCHEMA, TABLE_NAME"
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
                logger.warning("SQLServer get_metadata failed: %s", exc)
                return {"tables": [], "schemas": []}

        return await asyncio.to_thread(_probe)

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        drv = _load_driver()
        if drv is None:
            raise RuntimeError("pymssql not installed")
        if not (query or "").strip():
            raise ValueError("SQLServer execute_query requires a SQL statement")

        def _run() -> List[Dict[str, Any]]:
            conn = drv.connect(**_connect_params(config))
            try:
                cur = conn.cursor(as_dict=True)
                cur.execute(query)
                return list(cur.fetchall() or [])
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
            full = f"[{schema}].[{name}]" if schema else f"[{name}]"
            try:
                rows = await self.execute_query(config, f"SELECT COUNT(*) AS n FROM {full}")
                rows_by_table[f"{schema}.{name}" if schema else name] = int(rows[0].get("n", 0)) if rows else 0
            except Exception:
                rows_by_table[f"{schema}.{name}" if schema else name] = 0
        return {"success": True, "rows_by_table": rows_by_table}
