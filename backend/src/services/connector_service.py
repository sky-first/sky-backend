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
        }

        return connectors_registry.get(connector_id)

    def get_connectors(self) -> List[ConnectorResponse]:
        """
        Get all available connectors.

        Returns:
            List[ConnectorResponse]: List of connectors
        """
        connectors = []
        for connector_id in CONNECTORS.keys():
            definition = self._get_connector_definition(connector_id)
            if definition:
                connectors.append(self._convert_to_response(definition))

        return connectors

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
            fields=[
                ConnectorField(**field) for field in definition.get("fields", [])
            ],
            auth_methods=[
                AuthMethod(**method) for method in definition.get("auth_methods", [])
            ],
            config_schema=definition.get("config_schema", {}),
            sync_frequency=definition.get("sync_frequency"),
            metadata_schema=definition.get("metadata_schema"),
        )

