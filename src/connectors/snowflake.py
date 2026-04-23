"""Snowflake connector.

Uses the official ``snowflake-connector-python`` driver. The driver is
synchronous, so every call is wrapped in ``asyncio.to_thread`` to keep
the FastAPI event loop free. The driver is imported lazily: the module
itself imports cleanly even when ``snowflake-connector-python`` is not
installed — ``test_connection`` will then return False with an
informative log line, instead of crashing app startup.

Config::

    {
        "account": "xy12345.us-east-1",   # Snowflake account locator
        "username": "ANALYST",
        "password": "***",                 # basic auth
        "warehouse": "COMPUTE_WH",
        "database": "ANALYTICS",
        "schema": "PUBLIC",                # optional
        "role": "READ_ONLY",               # optional
    }
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _load_driver():
    """Import the Snowflake driver lazily so the app can boot even if
    the dep isn't installed (the registry entry will just report
    test_connection=False)."""
    try:
        import snowflake.connector as sf  # type: ignore

        return sf
    except Exception as exc:  # pragma: no cover - import error path
        logger.info("Snowflake driver not available: %s", exc)
        return None


def _connect_params(config: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "account": config.get("account"),
        "user": config.get("username") or config.get("user"),
        "password": config.get("password"),
        "warehouse": config.get("warehouse"),
        "database": config.get("database"),
    }
    if config.get("schema"):
        params["schema"] = config["schema"]
    if config.get("role"):
        params["role"] = config["role"]
    return params


class SnowflakeConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        sf = _load_driver()
        if sf is None:
            return False

        def _probe() -> bool:
            try:
                conn = sf.connect(**_connect_params(config))
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1")
                    row = cur.fetchone()
                    return bool(row and row[0] == 1)
                finally:
                    conn.close()
            except Exception as exc:
                logger.info("Snowflake test_connection failed: %s", exc)
                return False

        return await asyncio.to_thread(_probe)

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        sf = _load_driver()
        if sf is None:
            return {"tables": [], "schemas": []}

        def _probe() -> Dict[str, Any]:
            try:
                conn = sf.connect(**_connect_params(config))
                try:
                    cur = conn.cursor()
                    # INFORMATION_SCHEMA works across databases and is
                    # cheaper than SHOW TABLES for large accounts.
                    cur.execute(
                        "SELECT TABLE_SCHEMA, TABLE_NAME, ROW_COUNT "
                        "FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA') "
                        "ORDER BY TABLE_SCHEMA, TABLE_NAME"
                    )
                    rows = cur.fetchall() or []
                    schemas: List[str] = []
                    tables: List[Dict[str, Any]] = []
                    seen: set = set()
                    for schema, name, row_count in rows:
                        if schema not in seen:
                            schemas.append(schema)
                            seen.add(schema)
                        tables.append({
                            "name": name,
                            "schema": schema,
                            "row_count": int(row_count or 0),
                            "columns": [],
                        })
                    return {"tables": tables, "schemas": schemas}
                finally:
                    conn.close()
            except Exception as exc:
                logger.warning("Snowflake get_metadata failed: %s", exc)
                return {"tables": [], "schemas": []}

        return await asyncio.to_thread(_probe)

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        sf = _load_driver()
        if sf is None:
            raise RuntimeError("snowflake-connector-python not installed")
        if not (query or "").strip():
            raise ValueError("Snowflake execute_query requires a SQL statement")

        def _run() -> List[Dict[str, Any]]:
            conn = sf.connect(**_connect_params(config))
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
        """Row counts per table — same contract as other real connectors."""
        meta = await self.get_metadata(config)
        return {
            "success": True,
            "rows_by_table": {
                t["name"]: int(t.get("row_count") or 0)
                for t in meta.get("tables", [])
            },
        }
