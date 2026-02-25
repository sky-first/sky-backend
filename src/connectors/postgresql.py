"""PostgreSQL connector."""

from typing import Any, Dict, List, Optional

import asyncpg

from src.connectors.base import BaseConnector


class PostgreSQLConnector(BaseConnector):
    """PostgreSQL connector."""

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """Test PostgreSQL connection."""
        try:
            conn = await asyncpg.connect(
                host=config.get("host"),
                port=config.get("port", 5432),
                user=config.get("username"),
                password=config.get("password"),
                database=config.get("database"),
                timeout=2.0,
            )
            await conn.close()
            return True
        except Exception:
            return False

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Get PostgreSQL metadata."""
        conn = await asyncpg.connect(
            host=config.get("host"),
            port=config.get("port", 5432),
            user=config.get("username"),
            password=config.get("password"),
            database=config.get("database"),
            timeout=2.0,
        )
        try:
            # Queries to fetch tables, columns, and row counts
            # This is a simplified version; production might need more robust handling
            tables_query = """
                SELECT
                    table_schema,
                    table_name
                FROM
                    information_schema.tables
                WHERE
                    table_schema NOT IN ('information_schema', 'pg_catalog')
                    AND table_type = 'BASE TABLE'
            """
            tables = await conn.fetch(tables_query)

            result_tables = []
            schemas = set()

            for table in tables:
                schema = table["table_schema"]
                name = table["table_name"]
                schemas.add(schema)

                # Fetch columns
                columns_query = f"""
                    SELECT
                        column_name,
                        data_type,
                        is_nullable
                    FROM
                        information_schema.columns
                    WHERE
                        table_schema = '{schema}'
                        AND table_name = '{name}'
                """
                columns = await conn.fetch(columns_query)

                column_data = []
                for col in columns:
                    column_data.append({
                        "name": col["column_name"],
                        "type": col["data_type"],
                        "nullable": col["is_nullable"] == "YES",
                        "description": None  # Postgre doesn't store descriptions in information_schema easily
                    })

                # Fetch row count (approximate or exact)
                # Using count(*) can be slow on large tables; using pg_class for approximation
                # row_count_query = f"SELECT count(*) FROM {schema}.{name}"
                # row_count_result = await conn.fetchval(row_count_query)
                row_count_result = 0  # Placeholder for now to avoid performance hit

                result_tables.append({
                    "name": name,
                    "schema": schema,
                    "row_count": row_count_result,
                    "columns": column_data,
                    "last_updated": None,  # Database doesn't track this by default
                    "health": "Healthy",  # Default
                    "usage_score": 0,  # Default
                    "tags": []  # Default
                })

            return {"tables": result_tables, "schemas": list(schemas)}
        finally:
            await conn.close()

    async def execute_query(self, config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """Execute PostgreSQL query."""
        conn = await asyncpg.connect(
            host=config.get("host"),
            port=config.get("port", 5432),
            user=config.get("username"),
            password=config.get("password"),
            database=config.get("database"),
            timeout=2.0,
        )
        try:
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
