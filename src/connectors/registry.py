"""Connector registry."""

from typing import Dict, Type

from src.connectors.base import BaseConnector
from src.connectors.bigquery import BigQueryConnector


# Mock connectors for now - will be implemented later
class MockConnector(BaseConnector):
    """Mock connector for testing."""

    async def test_connection(self, config: Dict) -> bool:
        """Test connection - always returns True for now."""
        return True

    async def get_metadata(self, config: Dict) -> Dict:
        """Get metadata - returns empty metadata for now."""
        return {"tables": [], "schemas": []}

    async def execute_query(self, config: Dict, query: str) -> list:
        """Execute query - returns empty list for now."""
        return []

    async def sync_data(self, config: Dict, options: Dict = None) -> Dict:
        """Sync data - returns empty result for now."""
        return {"success": True}


# Registry of available connectors
CONNECTORS: Dict[str, Type[BaseConnector]] = {
    "postgresql": MockConnector,
    "mysql": MockConnector,
    "mongodb": MockConnector,
    "google-sheets": MockConnector,
    "rest-api": MockConnector,
    # Use real BigQuery connector
    "bigquery": BigQueryConnector,
    "snowflake": MockConnector,
    "redshift": MockConnector,
    "sqlserver": MockConnector,
    "oracle": MockConnector,
    "sqlite": MockConnector,
    "clickhouse": MockConnector,
    "databricks": MockConnector,
    # TODO: Implement real connectors
}


def get_connector(connector_id: str) -> BaseConnector:
    """
    Get connector instance by ID.

    Args:
        connector_id: Connector ID

    Returns:
        BaseConnector: Connector instance

    Raises:
        ValueError: If connector not found
    """
    connector_class = CONNECTORS.get(connector_id)
    if not connector_class:
        raise ValueError(f"Connector '{connector_id}' not found")
    return connector_class()
