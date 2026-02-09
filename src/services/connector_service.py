"""Connector service."""

from typing import Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from src.connectors.registry import CONNECTORS
from src.schemas.connector import AuthMethod, ConnectorField, ConnectorResponse


class ConnectorService:
    """Connector service."""

    def __init__(self, db: AsyncSession):
        """
        Initialize connector service.

        Args:
            db: Database session
        """
        self.db = db

    def _get_connector_definition(self, connector_id: str) -> Dict:
        """
        Get connector definition by ID.

        Args:
            connector_id: Connector ID

        Returns:
            Dict: Connector definition
        """
        # Define connector registry
        connectors_registry = {
            "postgresql": {
                "id": "postgresql",
                "name": "PostgreSQL",
                "category": "database",
                "description": "Connect to PostgreSQL database",
                "icon": "database",
                "fields": [
                    {
                        "key": "host",
                        "label": "Host",
                        "type": "text",
                        "required": True,
                        "placeholder": "localhost",
                    },
                    {
                        "key": "port",
                        "label": "Port",
                        "type": "number",
                        "required": True,
                        "placeholder": "5432",
                        "default": 5432,
                    },
                    {
                        "key": "database",
                        "label": "Database",
                        "type": "text",
                        "required": True,
                        "placeholder": "mydb",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "Username/Password",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "host": {"type": "string", "required": True},
                    "port": {"type": "number", "required": True},
                    "database": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "mysql": {
                "id": "mysql",
                "name": "MySQL",
                "category": "database",
                "description": "Connect to MySQL database",
                "icon": "database",
                "fields": [
                    {
                        "key": "host",
                        "label": "Host",
                        "type": "text",
                        "required": True,
                        "placeholder": "localhost",
                    },
                    {
                        "key": "port",
                        "label": "Port",
                        "type": "number",
                        "required": True,
                        "placeholder": "3306",
                        "default": 3306,
                    },
                    {
                        "key": "database",
                        "label": "Database",
                        "type": "text",
                        "required": True,
                        "placeholder": "mydb",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "Username/Password",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "host": {"type": "string", "required": True},
                    "port": {"type": "number", "required": True},
                    "database": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "mongodb": {
                "id": "mongodb",
                "name": "MongoDB",
                "category": "database",
                "description": "Connect to MongoDB database",
                "icon": "database",
                "fields": [
                    {
                        "key": "connection_string",
                        "label": "Connection String",
                        "type": "text",
                        "required": True,
                        "placeholder": "mongodb://localhost:27017",
                    },
                    {
                        "key": "database",
                        "label": "Database Name",
                        "type": "text",
                        "required": True,
                        "placeholder": "my_database",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "Connection String",
                        "fields": [],
                    },
                ],
                "config_schema": {
                    "connection_string": {"type": "string", "required": True},
                    "database": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "google-sheets": {
                "id": "google-sheets",
                "name": "Google Sheets",
                "category": "document",
                "description": "Connect to Google Sheets",
                "icon": "file-spreadsheet",
                "fields": [
                    {
                        "key": "spreadsheet_id",
                        "label": "Spreadsheet ID",
                        "type": "text",
                        "required": True,
                        "placeholder": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "oauth",
                        "label": "OAuth 2.0",
                        "fields": [],
                        "instructions": "Authenticate with Google OAuth",
                    },
                ],
                "config_schema": {
                    "spreadsheet_id": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "rest-api": {
                "id": "rest-api",
                "name": "REST API",
                "category": "api",
                "description": "Connect to REST API endpoints",
                "icon": "globe",
                "fields": [
                    {
                        "key": "base_url",
                        "label": "Base URL",
                        "type": "url",
                        "required": True,
                        "placeholder": "https://api.example.com",
                    },
                    {
                        "key": "api_version",
                        "label": "API Version",
                        "type": "text",
                        "required": False,
                        "placeholder": "v1",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "api_key",
                        "label": "API Key",
                        "fields": [
                            {
                                "key": "api_key",
                                "label": "API Key",
                                "type": "password",
                                "required": True,
                            },
                            {
                                "key": "header_name",
                                "label": "Header Name",
                                "type": "text",
                                "required": True,
                                "placeholder": "X-API-Key",
                            },
                        ],
                    },
                    {
                        "type": "bearer",
                        "label": "Bearer Token",
                        "fields": [
                            {
                                "key": "bearer_token",
                                "label": "Bearer Token",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                    {
                        "type": "basic",
                        "label": "Basic Auth",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                    {
                        "type": "none",
                        "label": "No Authentication",
                        "fields": [],
                    },
                ],
                "config_schema": {
                    "base_url": {"type": "string", "required": True},
                    "api_version": {"type": "string", "required": False},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "bigquery": {
                "id": "bigquery",
                "name": "Google BigQuery",
                "category": "database",
                "description": "Connect to Google BigQuery data warehouse",
                "icon": "database",
                "fields": [
                    {
                        "key": "project_id",
                        "label": "Project ID",
                        "type": "text",
                        "required": True,
                        "placeholder": "my-project-id",
                    },
                    {
                        "key": "dataset",
                        "label": "Dataset",
                        "type": "text",
                        "required": False,
                        "placeholder": "my_dataset",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "oauth",
                        "label": "OAuth 2.0",
                        "fields": [],
                        "instructions": "Authenticate with Google OAuth",
                    },
                    {
                        "type": "service_account",
                        "label": "Service Account JSON",
                        "fields": [
                            {
                                "key": "service_account_json",
                                "label": "Service Account JSON",
                                "type": "textarea",
                                "required": True,
                                "description": "Paste your service account JSON credentials",
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "project_id": {"type": "string", "required": True},
                    "dataset": {"type": "string", "required": False},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "snowflake": {
                "id": "snowflake",
                "name": "Snowflake",
                "category": "database",
                "description": "Connect to Snowflake data warehouse",
                "icon": "database",
                "fields": [
                    {
                        "key": "account",
                        "label": "Account",
                        "type": "text",
                        "required": True,
                        "placeholder": "xy12345.us-east-1",
                    },
                    {
                        "key": "warehouse",
                        "label": "Warehouse",
                        "type": "text",
                        "required": True,
                        "placeholder": "COMPUTE_WH",
                    },
                    {
                        "key": "database",
                        "label": "Database",
                        "type": "text",
                        "required": True,
                        "placeholder": "MY_DB",
                    },
                    {
                        "key": "schema",
                        "label": "Schema",
                        "type": "text",
                        "required": False,
                        "placeholder": "PUBLIC",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "Username/Password",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                    {
                        "type": "keypair",
                        "label": "Key Pair Authentication",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "private_key",
                                "label": "Private Key",
                                "type": "textarea",
                                "required": True,
                            },
                            {
                                "key": "private_key_passphrase",
                                "label": "Private Key Passphrase",
                                "type": "password",
                                "required": False,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "account": {"type": "string", "required": True},
                    "warehouse": {"type": "string", "required": True},
                    "database": {"type": "string", "required": True},
                    "schema": {"type": "string", "required": False},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "redshift": {
                "id": "redshift",
                "name": "Amazon Redshift",
                "category": "database",
                "description": "Connect to Amazon Redshift data warehouse",
                "icon": "database",
                "fields": [
                    {
                        "key": "host",
                        "label": "Host",
                        "type": "text",
                        "required": True,
                        "placeholder": "example-cluster.abc123.us-east-1.redshift.amazonaws.com",
                    },
                    {
                        "key": "port",
                        "label": "Port",
                        "type": "number",
                        "required": True,
                        "placeholder": "5439",
                        "default": 5439,
                    },
                    {
                        "key": "database",
                        "label": "Database",
                        "type": "text",
                        "required": True,
                        "placeholder": "dev",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "Username/Password",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                    {
                        "type": "iam",
                        "label": "IAM Authentication",
                        "fields": [
                            {
                                "key": "iam_role_arn",
                                "label": "IAM Role ARN",
                                "type": "text",
                                "required": True,
                                "placeholder": "arn:aws:iam::123456789012:role/RedshiftRole",
                            },
                            {
                                "key": "cluster_identifier",
                                "label": "Cluster Identifier",
                                "type": "text",
                                "required": True,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "host": {"type": "string", "required": True},
                    "port": {"type": "number", "required": True},
                    "database": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "sqlserver": {
                "id": "sqlserver",
                "name": "SQL Server",
                "category": "database",
                "description": "Connect to Microsoft SQL Server database",
                "icon": "database",
                "fields": [
                    {
                        "key": "host",
                        "label": "Host",
                        "type": "text",
                        "required": True,
                        "placeholder": "localhost",
                    },
                    {
                        "key": "port",
                        "label": "Port",
                        "type": "number",
                        "required": True,
                        "placeholder": "1433",
                        "default": 1433,
                    },
                    {
                        "key": "database",
                        "label": "Database",
                        "type": "text",
                        "required": True,
                        "placeholder": "master",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "SQL Server Authentication",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                    {
                        "type": "windows",
                        "label": "Windows Authentication",
                        "fields": [
                            {
                                "key": "domain",
                                "label": "Domain",
                                "type": "text",
                                "required": False,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "host": {"type": "string", "required": True},
                    "port": {"type": "number", "required": True},
                    "database": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "oracle": {
                "id": "oracle",
                "name": "Oracle Database",
                "category": "database",
                "description": "Connect to Oracle Database",
                "icon": "database",
                "fields": [
                    {
                        "key": "host",
                        "label": "Host",
                        "type": "text",
                        "required": True,
                        "placeholder": "localhost",
                    },
                    {
                        "key": "port",
                        "label": "Port",
                        "type": "number",
                        "required": True,
                        "placeholder": "1521",
                        "default": 1521,
                    },
                    {
                        "key": "service_name",
                        "label": "Service Name",
                        "type": "text",
                        "required": False,
                        "placeholder": "ORCL",
                    },
                    {
                        "key": "sid",
                        "label": "SID",
                        "type": "text",
                        "required": False,
                        "placeholder": "ORCL",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "Username/Password",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "host": {"type": "string", "required": True},
                    "port": {"type": "number", "required": True},
                    "service_name": {"type": "string", "required": False},
                    "sid": {"type": "string", "required": False},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "sqlite": {
                "id": "sqlite",
                "name": "SQLite",
                "category": "database",
                "description": "Connect to SQLite database file",
                "icon": "database",
                "fields": [
                    {
                        "key": "database_path",
                        "label": "Database File Path",
                        "type": "text",
                        "required": True,
                        "placeholder": "/path/to/database.db",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "none",
                        "label": "No Authentication",
                        "fields": [],
                    },
                ],
                "config_schema": {
                    "database_path": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "clickhouse": {
                "id": "clickhouse",
                "name": "ClickHouse",
                "category": "database",
                "description": "Connect to ClickHouse database",
                "icon": "database",
                "fields": [
                    {
                        "key": "host",
                        "label": "Host",
                        "type": "text",
                        "required": True,
                        "placeholder": "localhost",
                    },
                    {
                        "key": "port",
                        "label": "Port",
                        "type": "number",
                        "required": True,
                        "placeholder": "9000",
                        "default": 9000,
                    },
                    {
                        "key": "database",
                        "label": "Database",
                        "type": "text",
                        "required": True,
                        "placeholder": "default",
                    },
                ],
                "auth_methods": [
                    {
                        "type": "basic",
                        "label": "Username/Password",
                        "fields": [
                            {
                                "key": "username",
                                "label": "Username",
                                "type": "text",
                                "required": True,
                            },
                            {
                                "key": "password",
                                "label": "Password",
                                "type": "password",
                                "required": False,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "host": {"type": "string", "required": True},
                    "port": {"type": "number", "required": True},
                    "database": {"type": "string", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
            "databricks": {
                "id": "databricks",
                "name": "Databricks",
                "category": "database",
                "description": "Connect to Databricks SQL Warehouse or Compute Cluster",
                "icon": "database",
                "fields": [
                    {
                        "key": "server_hostname",
                        "label": "Server Hostname",
                        "type": "text",
                        "required": True,
                        "placeholder": "adb-12345.6.azuredatabricks.net",
                    },
                    {
                        "key": "http_path",
                        "label": "HTTP Path",
                        "type": "text",
                        "required": True,
                        "placeholder": "/sql/1.0/warehouses/abc12345",
                    },
                    {
                        "key": "port",
                        "label": "Port",
                        "type": "number",
                        "required": True,
                        "placeholder": "443",
                        "default": 443,
                    },
                ],
                "auth_methods": [
                    {
                        "type": "token",
                        "label": "Personal Access Token",
                        "fields": [
                            {
                                "key": "token",
                                "label": "Access Token",
                                "type": "password",
                                "required": True,
                            },
                        ],
                    },
                ],
                "config_schema": {
                    "server_hostname": {"type": "string", "required": True},
                    "http_path": {"type": "string", "required": True},
                    "port": {"type": "number", "required": True},
                },
                "sync_frequency": {
                    "default": "0 */6 * * *",
                    "options": ["0 */1 * * *", "0 */6 * * *", "0 0 * * *", "0 0 * * 0"],
                },
            },
        }

        return connectors_registry.get(connector_id)

    def get_connectors(self) -> List[ConnectorResponse]:
        """
        Get all available connectors.

        Returns:
            List[ConnectorResponse]: List of connectors
        """
        # Define the desired order for database connectors
        database_order = [
            "databricks",
            "mongodb",
            "bigquery",
            "redshift",
            "postgresql",
            "mysql",
            "oracle",
            "sqlite",
            "sqlserver",
            "snowflake",
            "clickhouse",
        ]

        # Separate database connectors from other connectors
        database_connectors = []
        other_connectors = []

        for connector_id in CONNECTORS.keys():
            definition = self._get_connector_definition(connector_id)
            if definition:
                connector_response = self._convert_to_response(definition)
                if definition.get("category") == "database":
                    database_connectors.append((connector_id, connector_response))
                else:
                    other_connectors.append(connector_response)

        # Sort database connectors according to the defined order
        ordered_databases = []
        for db_id in database_order:
            for connector_id, connector_response in database_connectors:
                if connector_id == db_id:
                    ordered_databases.append(connector_response)
                    break

        # Combine ordered databases with other connectors
        return ordered_databases + other_connectors

    def get_connector(self, connector_id: str) -> ConnectorResponse:
        """
        Get connector by ID.

        Args:
            connector_id: Connector ID

        Returns:
            ConnectorResponse: Connector data

        Raises:
            NotFoundError: If connector not found
        """
        from src.core.exceptions import NotFoundError

        definition = self._get_connector_definition(connector_id)
        if not definition:
            raise NotFoundError(f"Connector '{connector_id}' not found")

        return self._convert_to_response(definition)

    def get_categories(self) -> List[str]:
        """
        Get all connector categories.

        Returns:
            List[str]: List of categories
        """
        categories = set()
        for connector_id in CONNECTORS.keys():
            definition = self._get_connector_definition(connector_id)
            if definition:
                categories.add(definition["category"])

        return sorted(list(categories))

    def _convert_to_response(self, definition: Dict) -> ConnectorResponse:
        """
        Convert connector definition to response.

        Args:
            definition: Connector definition dict

        Returns:
            ConnectorResponse: Connector response
        """
        return ConnectorResponse(
            id=definition["id"],
            name=definition["name"],
            category=definition["category"],
            description=definition["description"],
            icon=definition.get("icon"),
            fields=[ConnectorField(**field) for field in definition.get("fields", [])],
            auth_methods=[AuthMethod(**method) for method in definition.get("auth_methods", [])],
            config_schema=definition.get("config_schema", {}),
            sync_frequency=definition.get("sync_frequency"),
            metadata_schema=definition.get("metadata_schema"),
        )
