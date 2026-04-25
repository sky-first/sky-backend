"""Connector registry."""

from typing import Any, Dict, Optional, Type

from src.connectors.base import BaseConnector
from src.connectors.bigquery import BigQueryConnector
from src.connectors.dropbox import DropboxConnector
from src.connectors.google_drive import GoogleDriveConnector
from src.connectors.google_sheets import GoogleSheetsConnector
from src.connectors.hubspot import HubSpotConnector
from src.connectors.jira import JiraConnector
from src.connectors.microsoft_graph import OneDriveConnector, SharePointConnector
from src.connectors.mongodb import MongoDBConnector
from src.connectors.mysql import MySQLConnector
from src.connectors.notion import NotionConnector
from src.connectors.postgresql import PostgreSQLConnector
from src.connectors.rest_api import RestAPIConnector
from src.connectors.salesforce import SalesforceConnector
from src.connectors.slack import SlackConnector
from src.connectors.sqlite import SQLiteConnector


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

    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Sync data - returns empty result for now."""
        return {"success": True}


# Registry of available connectors
CONNECTORS: Dict[str, Type[BaseConnector]] = {
    "postgresql": PostgreSQLConnector,
    "mysql": MySQLConnector,
    "mongodb": MongoDBConnector,
    "google-sheets": GoogleSheetsConnector,
    "google_sheets": GoogleSheetsConnector,
    "rest-api": RestAPIConnector,
    "rest_api": RestAPIConnector,
    "jira": JiraConnector,
    "hubspot": HubSpotConnector,
    "salesforce": SalesforceConnector,
    "google-drive": GoogleDriveConnector,
    "google_drive": GoogleDriveConnector,
    "dropbox": DropboxConnector,
    "onedrive": OneDriveConnector,
    "sharepoint": SharePointConnector,
    "slack": SlackConnector,
    "notion": NotionConnector,
    # Use real BigQuery connector
    "bigquery": BigQueryConnector,
    "snowflake": MockConnector,
    "redshift": MockConnector,
    "sqlserver": MockConnector,
    "oracle": MockConnector,
    "sqlite": SQLiteConnector,
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
