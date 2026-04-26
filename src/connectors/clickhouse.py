"""ClickHouse connector.

Uses ``clickhouse-driver`` (native TCP protocol, faster than HTTP).
Driver is sync, so calls are dispatched via ``asyncio.to_thread``.
Imported lazily.

Config::

    {
        "host": "clickhouse.internal",
        "port": 9000,                # native TCP port
        "database": "analytics",
        "username": "default",       # optional; CH default user is 'default'
        "password": "",              # optional
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
        from clickhouse_driver import Client  # type: ignore

        return Client
    except Exception as exc:  # pragma: no cover - import error path
        logger.info("clickhouse-driver not available: %s", exc)
        return None


def _client_kwargs(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "host": config.get("host"),
        "port": int(config.get("port") or 9000),
        "user": config.get("username") or config.get("user") or "default",
        "password": config.get("password") or "",
        "database": config.get("database") or "default",
        "connect_timeout": int(config.get("timeout", 10)),
    }


class ClickHouseConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        Client = _load_driver()
        if Client is None:
            return False

        def _probe() -> bool:
            try:
                client = Client(**_client_kwargs(config))
                try:
                    row = client.execute("SELECT 1")
                    return bool(row and row[0][0] == 1)
                finally:
                    client.disconnect()
            except Exception as exc:
                logger.info("ClickHouse test_connection failed: %s", exc)
                return False

        return await asyncio.to_thread(_probe)

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        Client = _load_driver()
        if Client is None:
            return {"tables": [], "schemas": []}

        def _probe() -> Dict[str, Any]:
            try:
                client = Client(**_client_kwargs(config))
                try:
                    rows = client.execute(
                        "SELECT database, name, total_rows "
                        "FROM system.tables "
                        "WHERE database NOT IN ('system', 'INFORMATION_SCHEMA') "
                        "ORDER BY database, name"
                    )
                    schemas: List[str] = []
                    tables: List[Dict[str, Any]] = []
                    seen: set = set()
                    for db_name, name, total_rows in rows or []:
                        if db_name not in seen:
                            schemas.append(db_name)
                            seen.add(db_name)
                        tables.append({
                            "name": name,
                            "schema": db_name,
                            "row_count": int(total_rows or 0),
                            "columns": [],
                        })
                    return {"tables": tables, "schemas": schemas}
                finally:
                    client.disconnect()
            except Exception as exc:
                logger.warning("ClickHouse get_metadata failed: %s", exc)
                return {"tables": [], "schemas": []}

        return await asyncio.to_thread(_probe)

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        Client = _load_driver()
        if Client is None:
            raise RuntimeError("clickhouse-driver not installed")
        if not (query or "").strip():
            raise ValueError("ClickHouse execute_query requires a SQL statement")

        def _run() -> List[Dict[str, Any]]:
            client = Client(**_client_kwargs(config))
            try:
                # `with_column_types=True` returns (rows, column_metadata)
                rows, cols_meta = client.execute(query, with_column_types=True)
                cols = [c[0] for c in cols_meta]
                return [dict(zip(cols, row)) for row in rows]
            finally:
                client.disconnect()

        return await asyncio.to_thread(_run)

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        meta = await self.get_metadata(config)
        return {
            "success": True,
            "rows_by_table": {
                f"{t['schema']}.{t['name']}" if t.get("schema") else t["name"]: int(t.get("row_count") or 0)
                for t in meta.get("tables", [])
            },
        }
