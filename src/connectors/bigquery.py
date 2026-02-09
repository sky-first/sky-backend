"""BigQuery connector implementation."""

from __future__ import annotations

import json
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

            query = f"""
            SELECT
              table_name,
              column_name,
              data_type,
              is_nullable
            FROM `{full_dataset}.INFORMATION_SCHEMA.COLUMNS`
            ORDER BY table_name, ordinal_position
            """

            job = client.query(query)
            rows = list(job.result())

            tables: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                table_name = str(row["table_name"])
                column_name = str(row["column_name"])
                data_type = str(row["data_type"])
                is_nullable = str(row["is_nullable"]).upper() == "YES"

                if table_name not in tables:
                    tables[table_name] = {
                        "name": table_name,
                        "schema": dataset,  # logical dataset/schema name
                        "row_count": None,
                        "columns": [],
                        "last_updated": None,
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
