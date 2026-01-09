"""Base connector interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseConnector(ABC):
    """Base connector interface for data sources."""

    @abstractmethod
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """
        Test connection to data source.

        Args:
            config: Connection configuration

        Returns:
            bool: True if connection successful
        """
        pass

    @abstractmethod
    async def get_metadata(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get metadata from data source.

        Args:
            config: Connection configuration

        Returns:
            Dict[str, Any]: Metadata (tables, schemas, etc.)
        """
        pass

    @abstractmethod
    async def execute_query(self, config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """
        Execute query on data source.

        Args:
            config: Connection configuration
            query: Query to execute

        Returns:
            List[Dict[str, Any]]: Query results
        """
        pass

    @abstractmethod
    async def sync_data(
        self, config: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Sync data from source.

        Args:
            config: Connection configuration
            options: Optional sync options

        Returns:
            Dict[str, Any]: Sync result
        """
        pass
