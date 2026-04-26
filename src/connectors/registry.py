"""Connector registry."""

from typing import Any, Dict, Optional, Type

from src.connectors.airtable import AirtableConnector
from src.connectors.azure_blob import AzureBlobConnector
from src.connectors.base import BaseConnector
from src.connectors.bigquery import BigQueryConnector
from src.connectors.confluence import ConfluenceConnector
from src.connectors.box import BoxConnector
from src.connectors.discord import DiscordConnector
from src.connectors.dropbox import DropboxConnector
from src.connectors.elasticsearch import ElasticsearchConnector
from src.connectors.gcs import GCSConnector
from src.connectors.github import GitHubConnector
from src.connectors.gitlab import GitLabConnector
from src.connectors.google_drive import GoogleDriveConnector
from src.connectors.google_sheets import GoogleSheetsConnector
from src.connectors.hubspot import HubSpotConnector
from src.connectors.jira import JiraConnector
from src.connectors.mailchimp import MailchimpConnector
from src.connectors.mariadb import MariaDBConnector
from src.connectors.microsoft_graph import OneDriveConnector, SharePointConnector
from src.connectors.mongodb import MongoDBConnector
from src.connectors.mysql import MySQLConnector
from src.connectors.notion import NotionConnector
from src.connectors.postgresql import PostgreSQLConnector
from src.connectors.rest_api import RestAPIConnector
from src.connectors.s3 import S3Connector
from src.connectors.salesforce import SalesforceConnector
from src.connectors.slack import SlackConnector
from src.connectors.sqlite import SQLiteConnector
from src.connectors.stripe import StripeConnector
from src.connectors.trello import TrelloConnector
from src.connectors.zendesk import ZendeskConnector


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
    "s3": S3Connector,
    "amazon-s3": S3Connector,
    "confluence": ConfluenceConnector,
    "gcs": GCSConnector,
    "google-cloud-storage": GCSConnector,
    "azure-blob": AzureBlobConnector,
    "azure_blob": AzureBlobConnector,
    "azure-blob-storage": AzureBlobConnector,
    "box": BoxConnector,
    # Use real BigQuery connector
    "bigquery": BigQueryConnector,
    "snowflake": MockConnector,
    "redshift": MockConnector,
    "sqlserver": MockConnector,
    "oracle": MockConnector,
    "sqlite": SQLiteConnector,
    "clickhouse": MockConnector,
    "databricks": MockConnector,
    # P2 — real REST drivers (Phase 2 of the connector roll-out).
    "github": GitHubConnector,
    "gitlab": GitLabConnector,
    "stripe": StripeConnector,
    "airtable": AirtableConnector,
    "mailchimp": MailchimpConnector,
    "trello": TrelloConnector,
    "discord": DiscordConnector,
    "zendesk": ZendeskConnector,
    "mariadb": MariaDBConnector,
    "elasticsearch": ElasticsearchConnector,
    "opensearch": ElasticsearchConnector,  # OpenSearch is wire-compatible
    # TODO: Implement real connectors for the remaining "Coming Soon"
    # entries — Snowflake / Redshift / SQL Server / Oracle / etc.
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
