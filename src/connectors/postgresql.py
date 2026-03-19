"""PostgreSQL connector."""

from typing import Any, Dict, List, Optional

import asyncpg

from src.connectors.base import BaseConnector


class PostgreSQLConnector(BaseConnector):
    """PostgreSQL connector."""

    def _get_connection_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize connection parameters from config."""
        return {
            "host": config.get("host"),
            "port": int(config.get("port") or 5432),
            "user": config.get("username"),
            "password": config.get("password"),
            "database": config.get("database"),
            "timeout": float(config.get("timeout", 5.0)),
        }

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """Test PostgreSQL connection using a context manager."""
        params = self._get_connection_params(config)
        try:
            async with asyncpg.connect(**params):
                pass
            return True
        except Exception:
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get PostgreSQL metadata including comments.

        Note: row_count is an estimate based on reltuples from pg_class for performance.
        """
        params = self._get_connection_params(config)
        async with asyncpg.connect(**params) as conn:
            # Better query using pg_catalog to get comments (descriptions)
            tables_query = """
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
            tables = await conn.fetch(tables_query)

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

    async def execute_query(self, config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """Execute PostgreSQL query using a context manager."""
        params = self._get_connection_params(config)
        async with asyncpg.connect(**params) as conn:
            rows = await conn.fetch(query)
            return [dict(row) for row in rows]

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Sync PostgreSQL data."""
        # TODO: Implement sync logic
        return {"status": "success"}
