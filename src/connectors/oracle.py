"""Oracle Database connector.

Uses ``oracledb`` in thin mode — no Oracle client libraries required.
Driver is sync, so calls are dispatched via ``asyncio.to_thread``.
Imported lazily so the app boots without the optional dep.

Config::

    {
        "host": "oracle.internal",
        "port": 1521,
        "service_name": "ORCLPDB",   # or "sid": "ORCL"
        "username": "ANALYTICS",
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
        import oracledb  # type: ignore

        return oracledb
    except Exception as exc:  # pragma: no cover - import error path
        logger.info("oracledb driver not available: %s", exc)
        return None


def _dsn_kwargs(config: Dict[str, Any]) -> Dict[str, Any]:
    """Build the kwargs oracledb.connect expects.

    Prefers ``service_name`` (the modern Oracle path); falls back to the
    legacy ``sid`` when that's what the user supplied.
    """
    kwargs: Dict[str, Any] = {
        "user": config.get("username") or config.get("user"),
        "password": config.get("password"),
        "host": config.get("host"),
        "port": int(config.get("port") or 1521),
    }
    if config.get("service_name"):
        kwargs["service_name"] = config["service_name"]
    elif config.get("sid"):
        kwargs["sid"] = config["sid"]
    return kwargs


class OracleConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        drv = _load_driver()
        if drv is None:
            return False

        def _probe() -> bool:
            try:
                conn = drv.connect(**_dsn_kwargs(config))
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1 FROM dual")
                    row = cur.fetchone()
                    return bool(row and row[0] == 1)
                finally:
                    conn.close()
            except Exception as exc:
                logger.info("Oracle test_connection failed: %s", exc)
                return False

        return await asyncio.to_thread(_probe)

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        drv = _load_driver()
        if drv is None:
            return {"tables": [], "schemas": []}

        def _probe() -> Dict[str, Any]:
            try:
                conn = drv.connect(**_dsn_kwargs(config))
                try:
                    cur = conn.cursor()
                    # user_tables only returns the current schema's tables;
                    # all_tables includes everything the user can read.
                    cur.execute(
                        "SELECT owner, table_name FROM all_tables "
                        "WHERE owner NOT IN ('SYS','SYSTEM','OUTLN','DBSNMP') "
                        "ORDER BY owner, table_name"
                    )
                    rows = cur.fetchall() or []
                    schemas: List[str] = []
                    tables: List[Dict[str, Any]] = []
                    seen: set = set()
                    for owner, name in rows:
                        if owner not in seen:
                            schemas.append(owner)
                            seen.add(owner)
                        tables.append({
                            "name": name,
                            "schema": owner,
                            "columns": [],
                        })
                    return {"tables": tables, "schemas": schemas}
                finally:
                    conn.close()
            except Exception as exc:
                logger.warning("Oracle get_metadata failed: %s", exc)
                return {"tables": [], "schemas": []}

        return await asyncio.to_thread(_probe)

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        drv = _load_driver()
        if drv is None:
            raise RuntimeError("oracledb not installed")
        if not (query or "").strip():
            raise ValueError("Oracle execute_query requires a SQL statement")

        def _run() -> List[Dict[str, Any]]:
            conn = drv.connect(**_dsn_kwargs(config))
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
                rows_by_table[full] = int(rows[0].get("N") or rows[0].get("n") or 0) if rows else 0
            except Exception:
                rows_by_table[full] = 0
        return {"success": True, "rows_by_table": rows_by_table}
