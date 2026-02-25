"""BigQuery connector implementation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseConnector


def _import_bigquery():
    """
    Lazy import for google-cloud-bigquery so the rest of the app works
    even if the dependency is missing.
    """
    try:
        from google.cloud import bigquery  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:  # pragma: no cover - runtime guard
        raise RuntimeError(
            "google-cloud-bigquery is required for the BigQuery connector. "
            "Install it with 'pip install google-cloud-bigquery'."
        ) from exc

    return bigquery, service_account


def _create_bq_client(config: Dict[str, Any]):
    """Create a BigQuery client from connection config."""
    bigquery, service_account = _import_bigquery()

    # service_account_json can be a JSON string or a dict
    sa_raw = config.get("service_account_json")
    credentials = None
    project_id = config.get("project_id")

    if sa_raw:
        if isinstance(sa_raw, str):
            sa_info = json.loads(sa_raw)
        elif isinstance(sa_raw, dict):
            sa_info = sa_raw
        else:
            raise ValueError(
                "service_account_json must be a JSON string or dict with the service account."
            )

        credentials = service_account.Credentials.from_service_account_info(sa_info)
        project_id = project_id or sa_info.get("project_id")

    if not project_id:
        raise ValueError("BigQuery config must include 'project_id'.")

    return bigquery.Client(project=project_id, credentials=credentials)


def _infer_dataset_from_config(config: Dict[str, Any]) -> str:
    """
    Infer default dataset from config.

    Expected fields:
      - config["dataset"]
      - or config["default_schema"] in format "project.dataset"
    """
    if "dataset" in config and config["dataset"]:
        return str(config["dataset"])

    default_schema = config.get("default_schema")
    if default_schema and isinstance(default_schema, str) and "." in default_schema:
        # project.dataset -> return dataset part
        return str(default_schema.split(".", 1)[1])

    raise ValueError(
        "Dataset not found in BigQuery config (expected 'dataset' or 'default_schema')."
    )


class BigQueryConnector(BaseConnector):
    """Real BigQuery connector using google-cloud-bigquery."""

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """
        Test connection by running a simple SELECT 1 query.
        """
        import asyncio

        def _run() -> bool:
            client = _create_bq_client(config)
            query_job = client.query("SELECT 1")
            list(query_job.result())
            return True

        return await asyncio.to_thread(_run)

    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get metadata (tables and schemas) from BigQuery INFORMATION_SCHEMA.

        Returns:
            {
              "tables": [
                {
                  "name": "table_name",
                  "schema": "dataset_name",
                  "row_count": null,
                  "columns": [
                    {"name": "...", "type": "...", "nullable": bool}
                  ]
                },
                ...
              ],
              "schemas": ["dataset_name"]
            }
        """
        import asyncio

        def _run() -> Dict[str, Any]:
            client = _create_bq_client(config)
            dataset = _infer_dataset_from_config(config)

            # Build full dataset path project.dataset
            project_id = client.project
            if "." in dataset and not dataset.startswith(f"{project_id}."):
                full_dataset = dataset
            elif "." in dataset and dataset.startswith(f"{project_id}."):
                full_dataset = dataset
            else:
                full_dataset = f"{project_id}.{dataset}"

            # 1. Fetch Columns
            columns_query = f"""
            SELECT
              table_name,
              column_name,
              data_type,
              is_nullable
            FROM `{full_dataset}.INFORMATION_SCHEMA.COLUMNS`
            ORDER BY table_name, ordinal_position
            """
            columns_job = client.query(columns_query)
            columns_rows = list(columns_job.result())

            # 2. Fetch Table Stats (row count, last modified)
            stats_query = f"SELECT table_id, row_count, last_modified_time FROM `{full_dataset}.__TABLES__`"
            stats_job = client.query(stats_query)
            stats_rows = {row["table_id"]: row for row in stats_job.result()}

            # 3. Fetch Usage (approximate from jobs last 30 days)
            # Use project region if available, otherwise fallback to project-level view (might need region prefix)
            # For simplicity, we'll try a generic query and fallback to Low if it fails
            usage_stats: Dict[str, str] = {}
            try:
                # We try to find the region of the dataset to query the correct JOBS_BY_PROJECT view
                ds_obj = client.get_dataset(dataset)
                region = ds_obj.location.lower() if ds_obj.location else "us"
                region_prefix = f"region-{region}"

                usage_query = f"""
                SELECT
                  referenced_table.table_id,
                  count(*) as query_count
                FROM
                  `{region_prefix}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`,
                  UNNEST(referenced_tables) AS referenced_table
                WHERE
                  creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
                  AND referenced_table.project_id = '{project_id}'
                  AND referenced_table.dataset_id = '{dataset}'
                GROUP BY 1
                """
                usage_job = client.query(usage_query)
                for row in usage_job.result():
                    count = row["query_count"]
                    if count > 100:
                        level = "High"
                    elif count > 20:
                        level = "Medium"
                    else:
                        level = "Low"
                    usage_stats[row["table_id"]] = level
            except Exception as e:
                print(f"Warning: Could not fetch usage stats: {e}")

            tables: Dict[str, Dict[str, Any]] = {}
            for row in columns_rows:
                table_name = str(row["table_name"])
                column_name = str(row["column_name"])
                data_type = str(row["data_type"])
                is_nullable = str(row["is_nullable"]).upper() == "YES"

                if table_name not in tables:
                    table_stats = stats_rows.get(table_name, {})
                    raw_last_mod = table_stats.get("last_modified_time")
                    last_updated = None
                    if raw_last_mod:
                        # BigQuery __TABLES__ last_modified_time is in milliseconds
                        last_updated = datetime.fromtimestamp(raw_last_mod / 1000.0, tz=timezone.utc).isoformat()

                    tables[table_name] = {
                        "name": table_name,
                        "schema": dataset,
                        "row_count": table_stats.get("row_count"),
                        "columns": [],
                        "last_updated": last_updated,
                        "usage": usage_stats.get(table_name, "Low"),
                    }

                tables[table_name]["columns"].append(
                    {
                        "name": column_name,
                        "type": data_type,
                        "nullable": is_nullable,
                    }
                )

            return {
                "tables": list(tables.values()),
                "schemas": [dataset],
            }

        return await asyncio.to_thread(_run)

    async def execute_query(self, config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """
        Execute an arbitrary SQL query against BigQuery and return rows as dicts.
        """
        import asyncio

        def _run() -> List[Dict[str, Any]]:
            client = _create_bq_client(config)
            job = client.query(query)
            return [dict(row) for row in job.result()]

        return await asyncio.to_thread(_run)

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Simple sync implementation that just refreshes metadata.
        """
        metadata = await self.get_metadata(config)
        return {
            "success": True,
            "tables_count": len(metadata.get("tables", [])),
            "schemas_count": len(metadata.get("schemas", [])),
        }
