"""SQLite connector.

Lightweight native connector using the `aiosqlite` driver that's
already in requirements.txt. Useful for local dev/staging data
fixtures and for users who genuinely have SQLite-based tooling —
not a warehouse, but a common enough shape to deserve real support.

Config:

    {
        "path": "/var/data/sales.sqlite",  # absolute path to the file
        "read_only": true,                  # default True (defensive)
    }

execute_query takes raw SQL. Read-only mode opens the file via URI
with `mode=ro` so arbitrary `DELETE` / `DROP` from an agent prompt
can't corrupt the DB.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import aiosqlite

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _connect_uri(path: str, read_only: bool) -> str:
    """Build a SQLite URI so we can set `mode=ro` for agent safety.

    aiosqlite passes through to sqlite3.connect which accepts URIs
    when uri=True.
    """
    if read_only:
        return f"file:{path}?mode=ro"
    return path


class SQLiteConnector(BaseConnector):
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        path = config.get("path")
        if not path:
            return False
        read_only = bool(config.get("read_only", True))
        if read_only and not os.path.exists(path):
            # Read-only mode fails if the file doesn't exist yet —
            # surface that as a clean False instead of a misleading
            # exception in the logs.
            return False
        try:
            async with aiosqlite.connect(_connect_uri(path, read_only), uri=True) as db:
                cur = await db.execute("SELECT 1")
                row = await cur.fetchone()
                return row is not None and row[0] == 1
        except Exception as exc:
            logger.info("SQLite test_connection failed (%s): %s", path, exc)
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        path = config.get("path")
        if not path:
            return {"tables": [], "schemas": []}
        read_only = bool(config.get("read_only", True))
        try:
            async with aiosqlite.connect(_connect_uri(path, read_only), uri=True) as db:
                cur = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
                rows = await cur.fetchall()
                table_names = [r[0] for r in rows]
                tables: List[Dict[str, Any]] = []
                for name in table_names:
                    info = await db.execute(f"PRAGMA table_info({name})")
                    cols_rows = await info.fetchall()
                    # cid, name, type, notnull, dflt_value, pk
                    columns = [
                        {"name": row[1], "type": row[2], "nullable": not bool(row[3])}
                        for row in cols_rows
                    ]
                    tables.append({
                        "name": name,
                        "kind": "sqlite_table",
                        "columns": columns,
                        "metadata": {},
                    })
                return {"tables": tables, "schemas": []}
        except Exception as exc:
            logger.warning("SQLite get_metadata failed: %s", exc)
            return {"tables": [], "schemas": []}

    async def execute_query(
        self, config: Dict[str, Any], query: str
    ) -> List[Dict[str, Any]]:
        path = config.get("path")
        if not path:
            raise ValueError("SQLite connector requires path")
        if not (query or "").strip():
            raise ValueError("SQLite execute_query requires a SQL statement")
        read_only = bool(config.get("read_only", True))
        async with aiosqlite.connect(_connect_uri(path, read_only), uri=True) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query)
            rows = await cur.fetchall()
            # Commit so writes survive context-manager close when
            # read_only=False. Reads are unaffected.
            if not read_only:
                await db.commit()
            return [dict(r) for r in rows]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Count rows in every table as the sync signal — same shape as
        the REST/Jira/Hubspot connectors return. Keeps the scheduler's
        sync contract consistent."""
        path = config.get("path")
        if not path:
            return {"success": False, "error": "missing path"}
        read_only = bool(config.get("read_only", True))
        rows_by_table: Dict[str, int] = {}
        try:
            async with aiosqlite.connect(_connect_uri(path, read_only), uri=True) as db:
                cur = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
                for (name,) in await cur.fetchall():
                    # Quote the identifier to survive reserved-word tables.
                    count_cur = await db.execute(f'SELECT COUNT(*) FROM "{name}"')
                    c = await count_cur.fetchone()
                    rows_by_table[name] = int(c[0]) if c else 0
            return {"success": True, "rows_by_table": rows_by_table}
        except Exception as exc:
            logger.warning("SQLite sync_data failed: %s", exc)
            return {"success": False, "error": str(exc)}
