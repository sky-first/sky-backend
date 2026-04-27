"""PostgreSQL connector."""

import re
import ssl as ssl_module
from typing import Any, Dict, List, Optional

import asyncpg

from src.connectors.base import BaseConnector

# Postgres identifier rule (unquoted): letter/_underscore + letters/digits/_
# Strict on purpose — the value is interpolated into SET search_path,
# which can't use bind parameters. Anything not matching is ignored.
_SCHEMA_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_schema(config: Dict[str, Any]) -> Optional[str]:
    """Return the configured schema name iff it's a valid Postgres
    identifier; otherwise None. Used to gate metadata filtering AND
    search_path setting against injection."""
    raw = (config.get("schema") or "").strip()
    if raw and _SCHEMA_IDENT_RE.match(raw):
        return raw
    return None


class PostgreSQLConnector(BaseConnector):
    """PostgreSQL connector."""

    def _get_connection_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize connection parameters from config.

        ssl_mode (FE form field) is mapped to asyncpg's `ssl` argument.
        asyncpg.connect() accepts `ssl=True | False | ssl.SSLContext`
        — strings like "require"/"prefer" are NOT recognized. Passing
        a string was silently treated as truthy by some code paths
        but the actual SSL handshake never fired, so Azure Postgres
        replied with `no pg_hba.conf entry for host …, no encryption`
        — surfaced (after #312/#315) as the user's failure to connect.

        Mapping:
          disable               → False (plain TCP)
          allow / prefer        → True  (SSL with default context)
          require               → True  (SSL with default context)
          verify-ca / verify-full → ssl.SSLContext with cert validation

        For Azure Postgres the public CA chain is in the system trust
        store, so the default SSLContext validates without extra root
        bundle wiring.
        """
        ssl_mode = (config.get("ssl_mode") or "prefer").strip().lower()
        ssl_param: Any
        if ssl_mode == "disable":
            ssl_param = False
        elif ssl_mode in ("verify-ca", "verify-full"):
            # Build a context that validates server cert against
            # system trust store. verify-full also checks hostname
            # — create_default_context() does both by default.
            ssl_param = ssl_module.create_default_context()
        else:
            # require / prefer / allow / unknown → SSL with default context
            ssl_param = True

        return {
            "host": config.get("host"),
            "port": int(config.get("port") or 5432),
            "user": config.get("username"),
            "password": config.get("password"),
            "database": config.get("database"),
            "timeout": float(config.get("timeout", 5.0)),
            "ssl": ssl_param,
        }

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """Test PostgreSQL connection.

        Intentionally does NOT swallow exceptions — the calling
        ConnectionService catches them and surfaces `str(exc)` as the
        UI message (handlers.py line 408). Swallowing here was the
        reason every Test Connection failure showed the useless
        "Connection test failed" placeholder regardless of whether
        the actual cause was wrong password, SSL handshake, host
        unreachable, or a typo'd database name.
        """
        # asyncpg.connect() is a coroutine that returns a Connection
        # — it is NOT itself an async context manager, so the original
        # `async with asyncpg.connect(...)` was always broken (the
        # try/except: return False that previously surrounded it just
        # hid the TypeError as a generic "Connection test failed").
        # Use the explicit await + close pattern instead.
        params = self._get_connection_params(config)
        conn = await asyncpg.connect(**params)
        try:
            pass  # successful connect proves the credentials work
        finally:
            await conn.close()
        return True

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get PostgreSQL metadata including comments.

        Note: row_count is an estimate based on reltuples from pg_class for performance.

        If config["schema"] is set to a valid identifier, only tables in
        that schema are returned. This is what makes the per-department
        Demo connections (e.g. `Demo — Sales` → schema crm) show only
        their schema's tables instead of the full multi-schema dataset.
        """
        params = self._get_connection_params(config)
        schema = _safe_schema(config)
        conn = await asyncpg.connect(**params)
        try:
            # Better query using pg_catalog to get comments (descriptions)
            base_query = """
                SELECT
                    n.nspname AS schema_name,
                    c.relname AS table_name,
                    obj_description(c.oid) AS description,
                    c.reltuples AS row_count
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('information_schema', 'pg_catalog')
                AND c.relkind = 'r'
            """
            if schema:
                tables = await conn.fetch(base_query + " AND n.nspname = $1", schema)
            else:
                tables = await conn.fetch(base_query)

            result_tables = []
            schemas = set()

            for table in tables:
                schema = table["schema_name"]
                name = table["table_name"]
                description = table["description"]
                row_count = int(table["row_count"]) if table["row_count"] else 0
                schemas.add(schema)

                # Fetch columns with comments using parameterized query ($1, $2)
                columns_query = """
                    SELECT
                        a.attname AS column_name,
                        format_type(a.atttypid, a.atttypmod) AS data_type,
                        NOT a.attnotnull AS is_nullable,
                        col_description(c.oid, a.attnum) AS description
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = $1
                    AND c.relname = $2
                    AND a.attnum > 0
                    AND NOT a.attisdropped
                """
                columns = await conn.fetch(columns_query, schema, name)

                column_data = []
                for col in columns:
                    column_data.append(
                        {
                            "name": col["column_name"],
                            "type": col["data_type"],
                            "nullable": col["is_nullable"],
                            "description": col["description"],
                        }
                    )

                result_tables.append(
                    {
                        "name": name,
                        "schema": schema,
                        "description": description,
                        "row_count": row_count,
                        "columns": column_data,
                        "last_updated": None,
                        "health": "Healthy",
                        "usage_score": 0,
                        "tags": [],
                    }
                )

            return {"tables": result_tables, "schemas": list(schemas)}
        finally:
            await conn.close()

    async def execute_query(self, config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """Execute PostgreSQL query using a context manager.

        If config["schema"] is set to a valid identifier, the session
        search_path is scoped to that schema (then `public` as fallback)
        before the query runs — so unqualified table references resolve
        to the configured schema. Schema name is regex-validated up
        front (asyncpg can't bind-param a SET command, so the value
        IS interpolated; the regex blocks injection).
        """
        params = self._get_connection_params(config)
        schema = _safe_schema(config)
        conn = await asyncpg.connect(**params)
        try:
            if schema:
                await conn.execute(f'SET search_path TO "{schema}", public')
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Sync PostgreSQL data."""
        # TODO: Implement sync logic
        return {"status": "success"}
