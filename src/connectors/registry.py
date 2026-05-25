"""Connector registry."""

from typing import Any, Dict, Optional, Type

from src.connectors.airtable import AirtableConnector
from src.connectors.azure_blob import AzureBlobConnector
from src.connectors.base import BaseConnector
from src.connectors.bigquery import BigQueryConnector
from src.connectors.box import BoxConnector
from src.connectors.clickhouse import ClickHouseConnector
from src.connectors.confluence import ConfluenceConnector
from src.connectors.databricks import DatabricksConnector
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
from src.connectors.oracle import OracleConnector
from src.connectors.postgresql import PostgreSQLConnector
from src.connectors.redshift import RedshiftConnector
from src.connectors.rest_api import RestAPIConnector
from src.connectors.s3 import S3Connector
from src.connectors.salesforce import SalesforceConnector
from src.connectors.slack import SlackConnector
from src.connectors.snowflake import SnowflakeConnector
from src.connectors.sqlite import SQLiteConnector
from src.connectors.sqlserver import SQLServerConnector
from src.connectors.stripe import StripeConnector
from src.connectors.trello import TrelloConnector
from src.connectors.zendesk import ZendeskConnector

# P2 batch 2 — REST adapter pack covering the long tail.
from src.connectors._p2_batch import (
    AmazonAthenaConnector,
    ApacheDruidConnector,
    CassandraConnector,
    ChromaConnector,
    CockroachDBConnector,
    CosmosDBConnector,
    CouchbaseConnector,
    DuckDBConnector,
    DynamoDBConnector,
    EvernoteConnector,
    FacebookAdsConnector,
    FacebookPagesConnector,
    FireboltConnector,
    GmailConnector,
    GoogleAdsConnector,
    HuggingFaceConnector,
    InstagramConnector,
    IntercomConnector,
    LinkedInPagesConnector,
    MicrosoftDynamicsConnector,
    MilvusConnector,
    Neo4jConnector,
    NetSuiteConnector,
    OutlookConnector,
    PineconeConnector,
    PlanetScaleConnector,
    PrestoConnector,
    QdrantConnector,
    QuickBooksConnector,
    RedisConnector,
    SapODataConnector,
    ServiceNowConnector,
    ShopifyConnector,
    SingleStoreConnector,
    SupabaseConnector,
    TeamsConnector,
    TeradataConnector,
    TiDBConnector,
    TrinoConnector,
    TwilioConnector,
    TwitterConnector,
    WeaviateConnector,
    WorkdayConnector,
    XeroConnector,
)


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
    "postgres": PostgreSQLConnector,
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
    # All six warehouses below now have real drivers. Each loads its
    # third-party dep lazily, so missing optional deps degrade to
    # test_connection=False rather than import-time crashes.
    "snowflake": SnowflakeConnector,
    "redshift": RedshiftConnector,
    "sqlserver": SQLServerConnector,
    "oracle": OracleConnector,
    "sqlite": SQLiteConnector,
    "clickhouse": ClickHouseConnector,
    "databricks": DatabricksConnector,
    # P2 batch 1 — real REST drivers.
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
    "opensearch": ElasticsearchConnector,
    # P2 batch 2 — REST-adapter pack (the long tail).
    "intercom": IntercomConnector,
    "shopify": ShopifyConnector,
    "quickbooks": QuickBooksConnector,
    "xero": XeroConnector,
    "dynamics": MicrosoftDynamicsConnector,
    "microsoft-dynamics": MicrosoftDynamicsConnector,
    "servicenow": ServiceNowConnector,
    "netsuite": NetSuiteConnector,
    "workday": WorkdayConnector,
    "sap-odata": SapODataConnector,
    "twilio": TwilioConnector,
    "twitter": TwitterConnector,
    "x": TwitterConnector,
    "gmail": GmailConnector,
    "outlook": OutlookConnector,
    "teams": TeamsConnector,
    "evernote": EvernoteConnector,
    "pinecone": PineconeConnector,
    "qdrant": QdrantConnector,
    "chroma": ChromaConnector,
    "weaviate": WeaviateConnector,
    "milvus": MilvusConnector,
    "huggingface": HuggingFaceConnector,
    "supabase": SupabaseConnector,
    "planetscale": PlanetScaleConnector,
    "cockroachdb": CockroachDBConnector,
    "tidb": TiDBConnector,
    "firebolt": FireboltConnector,
    "teradata": TeradataConnector,
    "cassandra": CassandraConnector,
    "couchbase": CouchbaseConnector,
    "cosmosdb": CosmosDBConnector,
    "cosmos-db": CosmosDBConnector,
    "dynamodb": DynamoDBConnector,
    "neo4j": Neo4jConnector,
    "redis": RedisConnector,
    "duckdb": DuckDBConnector,
    "presto": PrestoConnector,
    "trino": TrinoConnector,
    "singlestore": SingleStoreConnector,
    "athena": AmazonAthenaConnector,
    "amazon-athena": AmazonAthenaConnector,
    "druid": ApacheDruidConnector,
    "apache-druid": ApacheDruidConnector,
    "facebook-ads": FacebookAdsConnector,
    "facebook-pages": FacebookPagesConnector,
    "instagram": InstagramConnector,
    "linkedin": LinkedInPagesConnector,
    "google-ads": GoogleAdsConnector,
}


# Honest flag per connector: True when the backend has a real
# implementation (non-MockConnector). The UI reads this to show a
# "Real" badge vs a "Coming soon" pill so users don't pick a
# connector whose test_connection would silently return True on a
# mock but never actually execute queries.
def is_real_connector(connector_id: str) -> bool:
    cls = CONNECTORS.get(connector_id)
    return cls is not None and cls is not MockConnector


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
